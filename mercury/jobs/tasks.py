"""Short Procrastinate task wrappers around Mercury services.

Queue payloads carry only internal UUIDs and connection generations. Every task reloads the
owner/account relationship and re-checks the generation before provider work.

Recovery model (Procrastinate 3.9):
- Transient failures retry with capped exponential backoff and jitter (``MercuryRetry``);
  permanent failures (reauthorization, validation, denied label writes) are not retried.
- A run is marked ``failed`` with a safe error code when its job will not be retried, so the
  interface never claims that abandoned work is still progressing.
- ``queueing_lock`` coalesces duplicate waiting jobs; ``lock`` serializes one account's jobs
  without occupying extra worker slots.
- ``retry_stalled_jobs`` re-queues jobs whose worker stopped sending heartbeats (for example a
  killed container), which also releases their account lock.
"""

from __future__ import annotations

import re
import secrets
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import procrastinate
from flask import Flask
from googleapiclient.errors import HttpError
from procrastinate.exceptions import AlreadyEnqueued, ConnectorException
from procrastinate.jobs import Status
from sqlalchemy import or_, select, text

from mercury.accounts.models import GmailAccount
from mercury.buckets.organize import organize_account
from mercury.buckets.service import seed_demo_buckets
from mercury.extensions import db
from mercury.inbox.models import ProcessingRun
from mercury.inbox.service import index_account
from mercury.inbox.sync import account_lock, sync_account_history
from mercury.integrations.google.labels import LabelWriteDenied, apply_owned_label
from mercury.integrations.types import ProviderUnavailable, ReauthorizationRequired
from mercury.intelligence.service import analyze_pending

_flask_app: Flask | None = None

MAIL_ATTEMPTS = 5
MAINTENANCE_ATTEMPTS = 3
STALLED_RUN_AFTER = timedelta(minutes=15)
ABANDONED_RUN_AFTER = timedelta(hours=2)
STALLED_HEARTBEAT_SECONDS = 60
PERMANENT_ERRORS = (ReauthorizationRequired, LabelWriteDenied, LookupError, ValueError)
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


def bind_flask_app(app: Flask) -> None:
    global _flask_app
    _flask_app = app


def _app() -> Flask:
    if _flask_app is None:
        raise RuntimeError("worker Flask application is not bound")
    return _flask_app


class MercuryRetry(procrastinate.BaseRetryStrategy):
    """Capped exponential backoff with full jitter; provider Retry-After is honored."""

    def __init__(self, max_attempts: int, *, base_seconds: int = 5, cap_seconds: int = 900):
        self.max_attempts = max_attempts
        self.base_seconds = base_seconds
        self.cap_seconds = cap_seconds

    def is_retryable(self, exception: BaseException) -> bool:
        if isinstance(exception, HttpError):
            status = int(getattr(exception.resp, "status", 0) or 0)
            return status == 429 or status >= 500
        return not isinstance(exception, PERMANENT_ERRORS)

    def get_retry_decision(
        self, *, exception: BaseException, job
    ) -> procrastinate.RetryDecision | None:
        if job.attempts >= self.max_attempts or not self.is_retryable(exception):
            return None
        ceiling = min(self.cap_seconds, self.base_seconds * 2**job.attempts)
        delay = self.base_seconds + secrets.randbelow(max(1, ceiling))
        if isinstance(exception, ProviderUnavailable) and exception.retry_after:
            delay = max(delay, exception.retry_after)
        return procrastinate.RetryDecision(retry_in={"seconds": min(delay, self.cap_seconds)})


MAIL_RETRY = MercuryRetry(MAIL_ATTEMPTS)
MAINTENANCE_RETRY = MercuryRetry(MAINTENANCE_ATTEMPTS)
LABEL_RETRY = MercuryRetry(3)


def safe_error_code(exception: BaseException) -> str:
    """Return a short code for users/operators; never provider bodies or exception text."""
    if isinstance(exception, HttpError):
        status = int(getattr(exception.resp, "status", 0) or 0)
        return "provider_rate_limited" if status == 429 else "provider_unavailable"
    code = str(exception.args[0]) if exception.args else ""
    if isinstance(exception, (ReauthorizationRequired, ProviderUnavailable, LabelWriteDenied)):
        return code if _SAFE_CODE.match(code) else "provider_unavailable"
    if isinstance(exception, (ValueError, LookupError)) and _SAFE_CODE.match(code):
        return code
    return "processing_failed"


@contextmanager
def track_run(run_id: str | None, context: procrastinate.JobContext, strategy: MercuryRetry):
    """Record a safe error on the run; mark it failed once the job will not be retried."""
    try:
        yield
    except Exception as exc:
        db.session.rollback()
        if run_id:
            run = db.session.get(ProcessingRun, uuid.UUID(run_id))
            if run is not None and run.status not in {"succeeded", "failed"}:
                run.safe_error_code = safe_error_code(exc)
                if strategy.get_retry_decision(exception=exc, job=context.job) is None:
                    run.status = "failed"
                    run.stage = "failed"
                    run.finished_at = datetime.now(UTC)
                else:
                    run.stage = "retrying"
                db.session.commit()
        raise


def discover_recent_threads(
    context: procrastinate.JobContext, *, account_id: str, connection_generation: int, run_id: str
) -> None:
    app = _app()
    with app.app_context(), track_run(run_id, context, MAIL_RETRY):
        account_uuid = uuid.UUID(account_id)
        with account_lock(account_uuid):
            account = db.session.get(GmailAccount, account_uuid)
            run = db.session.get(ProcessingRun, uuid.UUID(run_id))
            if (
                account is None
                or run is None
                or run.gmail_account_id != account.id
                or account.connection_generation != connection_generation
                or run.status in {"succeeded", "failed"}
            ):
                return
            index_account(account, run, limit=run.requested_limit, finalize=False)
            if account.ai_consent and app.config["AI_PROCESSING_ENABLED"]:
                run.stage = "analyzing"
                db.session.commit()
                analyze_pending(account.user_id, onboarding=run.kind == "initial")
                run = db.session.get(ProcessingRun, run.id)
                run.stage = "discovering_buckets"
                db.session.commit()
                organize_account(account)
            if app.config["MAIL_MODE"] == "fake":
                seed_demo_buckets(account)
            run = db.session.get(ProcessingRun, run.id)
            run.stage = "complete"
            run.status = "succeeded"
            run.safe_error_code = None
            run.finished_at = datetime.now(UTC)
            db.session.commit()


def sync_account_history_task(
    context: procrastinate.JobContext,
    *,
    account_id: str,
    connection_generation: int,
    run_id: str | None = None,
) -> None:
    app = _app()
    with app.app_context(), track_run(run_id, context, MAIL_RETRY):
        analyze = app.config["AI_PROCESSING_ENABLED"]
        # With analysis to follow, the run stays open so progress polling does not stop early.
        sync_account_history(
            uuid.UUID(account_id),
            connection_generation,
            uuid.UUID(run_id) if run_id else None,
            finalize=not analyze,
        )
        account_uuid = uuid.UUID(account_id)
        with account_lock(account_uuid):
            account = db.session.get(GmailAccount, account_uuid)
            current = (
                account is not None
                and account.connection_generation == connection_generation
                and account.connection_state == "connected"
            )
            run = db.session.get(ProcessingRun, uuid.UUID(run_id)) if run_id else None
            if current and analyze and account.ai_consent:
                if run:
                    run.stage = "analyzing"
                    run.status = "running"
                    run.finished_at = None
                    db.session.commit()
                analyze_pending(account.user_id)
                if run:
                    run = db.session.get(ProcessingRun, run.id)
                    run.stage = "discovering_buckets"
                    db.session.commit()
                organize_account(account)
            if run and current:
                run = db.session.get(ProcessingRun, run.id)
                if run.status not in {"succeeded", "failed"}:
                    run.stage = "complete"
                    run.status = "succeeded"
                    run.safe_error_code = None
                    run.finished_at = datetime.now(UTC)
                    db.session.commit()


def apply_owned_label_task(
    *,
    account_id: str,
    user_id: str,
    thread_id: str,
    bucket_id: str | None,
    connection_generation: int,
) -> None:
    with _app().app_context():
        with account_lock(uuid.UUID(account_id)):
            apply_owned_label(
                account_id=uuid.UUID(account_id),
                user_id=uuid.UUID(user_id),
                thread_id=uuid.UUID(thread_id),
                bucket_id=uuid.UUID(bucket_id) if bucket_id else None,
                connection_generation=connection_generation,
            )


def reconcile_pending_work(timestamp: int | None = None) -> None:
    """Find durable pending work and (re-)enqueue it; see the module docstring."""
    del timestamp  # Supplied by Procrastinate's periodic scheduler; unused.
    app = _app()
    with app.app_context():
        reconcile(app)


def reconcile(app: Flask) -> dict[str, int]:
    now = datetime.now(UTC)
    queue_app = app.extensions["mercury"]["queue"]
    counts = {"recovered": 0, "abandoned": 0, "discovery": 0, "sync": 0}

    running = db.session.scalars(
        select(ProcessingRun).where(
            ProcessingRun.status == "running", ProcessingRun.created_at < now - STALLED_RUN_AFTER
        )
    ).all()
    for run in running:
        if _has_live_job(run):
            # Large imports legitimately run past STALLED_RUN_AFTER. A job that is still queued
            # or executing is alive; a dead worker's job is re-queued by retry_stalled_jobs.
            continue
        if run.created_at < now - ABANDONED_RUN_AFTER:
            # Bounded recovery: an old run that never completed is reported, not retried forever.
            run.status = "failed"
            run.stage = "failed"
            run.safe_error_code = "processing_stalled"
            run.finished_at = now
            counts["abandoned"] += 1
        else:
            run.status = "pending"
            run.stage = "recovered_after_stall"
            counts["recovered"] += 1
    db.session.commit()

    pending = db.session.scalars(
        select(ProcessingRun)
        .where(ProcessingRun.status == "pending")
        .order_by(ProcessingRun.created_at)
        .limit(100)
    ).all()
    for run in pending:
        account = db.session.get(GmailAccount, run.gmail_account_id)
        if account and account.connection_state == "connected":
            # Incremental runs resume as incremental work; only full runs re-list the mailbox.
            if run.kind == "sync":
                if enqueue_sync(queue_app, account, run) is not None:
                    counts["sync"] += 1
            elif enqueue_discovery(queue_app, account, run) is not None:
                counts["discovery"] += 1

    due = [GmailAccount.pending_sync.is_(True)]
    if app.config["SYNC_MODE"] in {"poll", "push"}:
        # Periodic catch-up sync is required even with push; poll mode relies on it entirely.
        stale_before = now - timedelta(seconds=app.config["SYNC_INTERVAL_SECONDS"])
        due += [GmailAccount.last_synced_at.is_(None), GmailAccount.last_synced_at < stale_before]
    accounts = db.session.scalars(
        select(GmailAccount)
        .where(GmailAccount.connection_state == "connected", or_(*due))
        .order_by(GmailAccount.last_synced_at.asc().nulls_first())
        .limit(100)
    ).all()
    for account in accounts:
        if enqueue_sync(queue_app, account) is not None:
            counts["sync"] += 1
    return counts


def _has_live_job(run: ProcessingRun) -> bool:
    locks = [_discovery_lock(run.id), _sync_lock(run.gmail_account_id, run.id)]
    return bool(
        db.session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM procrastinate_jobs"
                " WHERE queueing_lock = ANY(:locks) AND status IN ('todo', 'doing'))"
            ),
            {"locks": locks},
        )
    )


async def retry_stalled_jobs(context: procrastinate.JobContext, timestamp: int | None = None):
    """Re-queue jobs owned by workers that stopped heartbeating (crash or forced kill)."""
    del timestamp
    manager = context.app.job_manager
    stalled = await manager.get_stalled_jobs(seconds_since_heartbeat=STALLED_HEARTBEAT_SECONDS)
    for job in stalled:
        try:
            await manager.retry_job(job)
        except ConnectorException:
            # An identical job is already waiting (queueing lock). Finishing the stalled copy
            # releases its account lock so the waiting duplicate can run instead.
            await manager.finish_job(job, status=Status.FAILED, delete_job=False)


def renew_gmail_watches(timestamp: int | None = None) -> None:
    del timestamp
    app = _app()
    if app.config["SYNC_MODE"] != "push":
        return
    with app.app_context():
        account_ids = db.session.scalars(
            select(GmailAccount.id).where(GmailAccount.connection_state == "connected").limit(1000)
        ).all()
        failures = 0
        for account_id in account_ids:
            try:
                renew_watch(app, account_id)
            except (ProviderUnavailable, ReauthorizationRequired, HttpError):
                # One mailbox must not block renewal for the rest; stale sync is surfaced per
                # account and the next daily run tries again well before the 7-day expiry.
                db.session.rollback()
                failures += 1
        if failures:
            app.logger.warning(
                "watch_renewal_partial",
                extra={"event_type": "watch_renewal_partial", "count": failures},
            )


def renew_watch(app: Flask, account_id: uuid.UUID) -> None:
    account = db.session.get(GmailAccount, account_id)
    if account is None or account.connection_state != "connected":
        return
    generation = account.connection_generation
    result = app.extensions["mercury"]["mail_provider"](account).watch(app.config["PUBSUB_TOPIC"])
    db.session.refresh(account)
    if account.connection_generation != generation or account.connection_state != "connected":
        return
    account.watch_expires_at = datetime.fromtimestamp(int(result["expiration"]) / 1000, UTC)
    # Never move the checkpoint backwards: history sync owns last_history_id once it exists.
    if not account.last_history_id and result.get("historyId"):
        account.last_history_id = str(result["historyId"])
    db.session.commit()


def build_blueprint() -> procrastinate.Blueprint:
    """Register the task functions on a fresh Blueprint.

    ``App.add_tasks_from`` renames the tasks of the Blueprint it copies, so a shared module-level
    Blueprint breaks when one process builds two Apps (the web-side enqueue App inside
    ``create_app`` and the worker App). Each App therefore gets its own Blueprint.
    """
    bp = procrastinate.Blueprint()
    bp.task(name="discover_recent_threads", queue="mail", retry=MAIL_RETRY, pass_context=True)(
        discover_recent_threads
    )
    bp.task(name="sync_account_history", queue="mail", retry=MAIL_RETRY, pass_context=True)(
        sync_account_history_task
    )
    bp.task(name="apply_owned_label", queue="mail", retry=LABEL_RETRY)(apply_owned_label_task)
    bp.periodic(cron="*/5 * * * *")(
        bp.task(
            name="reconcile_pending_work",
            queue="maintenance",
            retry=MAINTENANCE_RETRY,
            queueing_lock="reconcile_pending_work",
        )(reconcile_pending_work)
    )
    bp.periodic(cron="*/2 * * * *")(
        bp.task(
            name="retry_stalled_jobs",
            queue="maintenance",
            pass_context=True,
            queueing_lock="retry_stalled_jobs",
        )(retry_stalled_jobs)
    )
    bp.periodic(cron="17 3 * * *")(
        bp.task(name="renew_gmail_watches", queue="maintenance", retry=MAINTENANCE_RETRY)(
            renew_gmail_watches
        )
    )
    return bp


def _defer(queue_app, task_name: str, *, lock: str, queueing_lock: str, **kwargs) -> int | None:
    """Defer a job; return None when an identical job is already waiting (coalesced)."""
    with queue_app.open():
        try:
            return queue_app.configure_task(
                task_name, lock=lock, queueing_lock=queueing_lock
            ).defer(**kwargs)
        except AlreadyEnqueued:
            return None


def _discovery_lock(run_id) -> str:
    return f"discover:{run_id}"


def _sync_lock(account_id, run_id) -> str:
    return f"sync:{account_id}:{run_id or 'catch-up'}"


def enqueue_discovery(queue_app, account: GmailAccount, run: ProcessingRun) -> int | None:
    return _defer(
        queue_app,
        "mercury:discover_recent_threads",
        lock=f"account:{account.id}",
        queueing_lock=_discovery_lock(run.id),
        account_id=str(account.id),
        connection_generation=account.connection_generation,
        run_id=str(run.id),
    )


def enqueue_sync(queue_app, account: GmailAccount, run: ProcessingRun | None = None) -> int | None:
    return _defer(
        queue_app,
        "mercury:sync_account_history",
        lock=f"account:{account.id}",
        queueing_lock=_sync_lock(account.id, run.id if run else None),
        account_id=str(account.id),
        connection_generation=account.connection_generation,
        run_id=str(run.id) if run else None,
    )


def enqueue_label(queue_app, account: GmailAccount, *, thread_id, bucket_id) -> int | None:
    bucket_key = str(bucket_id) if bucket_id else "unsorted"
    return _defer(
        queue_app,
        "mercury:apply_owned_label",
        lock=f"account:{account.id}",
        queueing_lock=f"label:{thread_id}:{bucket_key}",
        account_id=str(account.id),
        user_id=str(account.user_id),
        thread_id=str(thread_id),
        bucket_id=str(bucket_id) if bucket_id else None,
        connection_generation=account.connection_generation,
    )
