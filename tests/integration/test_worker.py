"""Real Procrastinate execution against PostgreSQL: one-shot workers, retries, and recovery."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from mercury.accounts.models import GmailAccount
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ProcessingRun
from mercury.inbox.service import index_account
from mercury.integrations.fake_gmail import FIXTURE_THREADS
from mercury.integrations.types import (
    ProviderUnavailable,
    ReauthorizationRequired,
    ThreadDiscovery,
)
from mercury.jobs import tasks as task_module
from mercury.jobs.queue import create_queue_app
from mercury.jobs.tasks import MAIL_ATTEMPTS, bind_flask_app, enqueue_discovery, reconcile
from tests.conftest import TEST_DATABASE_URL, csrf_token


def _new_run(account: GmailAccount, *, status: str = "pending", age=timedelta(0)):
    run = ProcessingRun(
        user_id=account.user_id,
        gmail_account_id=account.id,
        kind="manual",
        requested_limit=50,
        status=status,
        created_at=datetime.now(UTC) - age,
    )
    db.session.add(run)
    db.session.commit()
    return run


def _jobs(task_name: str | None = None) -> list:
    query = "SELECT id, status, attempts, lock, queueing_lock, args FROM procrastinate_jobs"
    params = {}
    if task_name:
        query += " WHERE task_name = :task_name"
        params["task_name"] = task_name
    return db.session.execute(text(query + " ORDER BY id"), params).all()


def _run_one_shot_worker(app, queues=("mail",)) -> None:
    """Drain currently runnable jobs with the same worker wiring as production, then return."""
    bind_flask_app(app)
    worker_app = create_queue_app(app.config["SQLALCHEMY_DATABASE_URI"], worker=True)
    worker_app.run_worker(
        queues=list(queues), wait=False, install_signal_handlers=False, listen_notify=False
    )


def test_one_shot_worker_executes_discovery_job(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = _new_run(account)
        run_id = run.id
        assert enqueue_discovery(app.extensions["mercury"]["queue"], account, run) is not None
        db.session.remove()

    _run_one_shot_worker(app)

    with app.app_context():
        run = db.session.get(ProcessingRun, run_id)
        assert (run.status, run.stage) == ("succeeded", "complete")
        assert run.completed_count > 0
        [job] = _jobs("mercury:discover_recent_threads")
        assert job.status == "succeeded"
        assert job.lock == f"account:{account.id}"


def test_duplicate_enqueue_is_coalesced(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = _new_run(account)
        queue = app.extensions["mercury"]["queue"]
        assert enqueue_discovery(queue, account, run) is not None
        assert enqueue_discovery(queue, account, run) is None
        assert len(_jobs("mercury:discover_recent_threads")) == 1


def test_transient_failure_schedules_backoff_retry_with_safe_code(app, connected, monkeypatch):
    def unavailable(*args, **kwargs):
        raise ProviderUnavailable("provider_rate_limited", retry_after=30)

    monkeypatch.setattr(task_module, "index_account", unavailable)
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = _new_run(account)
        run_id = run.id
        enqueue_discovery(app.extensions["mercury"]["queue"], account, run)
        db.session.remove()

    _run_one_shot_worker(app)

    with app.app_context():
        run = db.session.get(ProcessingRun, run_id)
        assert run.stage == "retrying"
        assert run.status == "pending"
        assert run.safe_error_code == "provider_rate_limited"
        [job] = _jobs("mercury:discover_recent_threads")
        assert (job.status, job.attempts) == ("todo", 1)
        scheduled = db.session.scalar(
            text("SELECT scheduled_at FROM procrastinate_jobs WHERE id = :id"), {"id": job.id}
        )
        # Retry-After (30s) is honored as the minimum delay.
        assert scheduled >= datetime.now(UTC) + timedelta(seconds=20)


def test_discovery_persists_each_thread_before_a_transient_stream_failure(
    app, connected, monkeypatch
):
    message = replace(
        FIXTURE_THREADS[0].messages[0],
        id="partial-progress-message",
        internet_message_id="<partial-progress-message@fixtures.invalid>",
    )
    thread = replace(FIXTURE_THREADS[0], id="partial-progress-thread", messages=(message,))

    class PartialProvider:
        def list_threads(self, *, limit, after_epoch):
            del limit, after_epoch

            def stream():
                yield thread
                raise ProviderUnavailable("provider_rate_limited", retry_after=60)

            return ThreadDiscovery(estimated_count=2, threads=stream())

    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = _new_run(account)
        monkeypatch.setitem(
            app.extensions["mercury"], "mail_provider", lambda _account: PartialProvider()
        )

        with pytest.raises(ProviderUnavailable, match="provider_rate_limited"):
            index_account(account, run, limit=2)
        db.session.rollback()

        db.session.refresh(run)
        assert (run.found_count, run.completed_count) == (2, 1)
        assert db.session.scalar(
            select(EmailThread).where(EmailThread.gmail_thread_id == "partial-progress-thread")
        )


def test_permanent_failure_is_not_retried_and_run_is_failed(app, connected, monkeypatch):
    def revoked(*args, **kwargs):
        raise ReauthorizationRequired("connection_needs_reauthorization")

    monkeypatch.setattr(task_module, "index_account", revoked)
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = _new_run(account)
        run_id = run.id
        enqueue_discovery(app.extensions["mercury"]["queue"], account, run)
        db.session.remove()

    _run_one_shot_worker(app)

    with app.app_context():
        run = db.session.get(ProcessingRun, run_id)
        assert (run.status, run.safe_error_code) == ("failed", "connection_needs_reauthorization")
        assert run.finished_at is not None
        [job] = _jobs("mercury:discover_recent_threads")
        assert job.status == "failed"


def test_final_transient_attempt_marks_run_failed(app, connected, monkeypatch):
    monkeypatch.setattr(
        task_module, "index_account", lambda *a, **k: (_ for _ in ()).throw(TimeoutError())
    )
    bind_flask_app(app)
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = _new_run(account)
        args = {
            "account_id": str(account.id),
            "connection_generation": account.connection_generation,
            "run_id": str(run.id),
        }
        run_id = run.id
        db.session.remove()
    context = SimpleNamespace(job=SimpleNamespace(attempts=MAIL_ATTEMPTS))
    with pytest.raises(TimeoutError):
        task_module.discover_recent_threads(context, **args)
    with app.app_context():
        run = db.session.get(ProcessingRun, run_id)
        assert (run.status, run.safe_error_code) == ("failed", "processing_failed")


def test_stale_generation_job_does_not_index(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = _new_run(account)
        run_id = run.id
        enqueue_discovery(app.extensions["mercury"]["queue"], account, run)
        account.connection_generation += 1
        db.session.commit()
        db.session.remove()

    _run_one_shot_worker(app)

    with app.app_context():
        run = db.session.get(ProcessingRun, run_id)
        assert (run.status, run.completed_count) == ("pending", 0)


def test_reconcile_recovers_work_after_enqueue_failure(app, connected):
    """A run committed without a queue job (enqueue failed) is found and completed later."""
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = _new_run(account)
        run_id = run.id
        assert _jobs() == []
        assert reconcile(app)["discovery"] == 1
        assert reconcile(app)["discovery"] == 0  # Coalesced while the first job waits.
        db.session.remove()

    _run_one_shot_worker(app)

    with app.app_context():
        assert db.session.get(ProcessingRun, run_id).status == "succeeded"


def test_reconcile_bounds_stalled_runs(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        recent = _new_run(account, status="running", age=timedelta(minutes=20))
        abandoned = _new_run(account, status="running", age=timedelta(hours=3))
        fresh = _new_run(account, status="running", age=timedelta(minutes=1))
        counts = reconcile(app)
        assert (counts["recovered"], counts["abandoned"]) == (1, 1)
        assert (recent.status, recent.stage) == ("pending", "recovered_after_stall")
        assert (abandoned.status, abandoned.safe_error_code) == ("failed", "processing_stalled")
        assert fresh.status == "running"


def test_reconcile_poll_mode_schedules_catch_up_sync(app, connected, monkeypatch):
    monkeypatch.setitem(app.config, "SYNC_MODE", "poll")
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        account.last_synced_at = datetime.now(UTC) - timedelta(hours=1)
        db.session.commit()
        assert reconcile(app)["sync"] == 1
        assert reconcile(app)["sync"] == 0
        [job] = _jobs("mercury:sync_account_history")
        assert str(account.id) in str(job.args)

        account.last_synced_at = datetime.now(UTC)
        db.session.execute(text("DELETE FROM procrastinate_jobs"))
        db.session.commit()
        assert reconcile(app)["sync"] == 0


def test_manual_mode_does_not_poll(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        account.last_synced_at = datetime.now(UTC) - timedelta(days=1)
        db.session.commit()
        assert reconcile(app)["sync"] == 0


def test_killed_worker_job_is_recovered_by_heartbeat(app, connected, monkeypatch):
    """SIGKILL a worker mid-job; the stalled job is re-queued and then completes."""
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = _new_run(account)
        run_id, account_id = run.id, account.id
        enqueue_discovery(app.extensions["mercury"]["queue"], account, run)
        db.session.remove()

    # Hold the account's advisory lock so the worker blocks inside the job.
    with app.app_context():
        holder = db.engine.connect()
        holder.execute(text("SELECT pg_advisory_lock(hashtext(:k))"), {"k": str(account_id)})
        env = {
            **os.environ,
            "APP_ENV": "testing",
            "APP_BASE_URL": "http://localhost:5000",
            "DATABASE_URL": TEST_DATABASE_URL,
        }
        worker = subprocess.Popen(  # noqa: S603 - fixed interpreter and module
            [
                sys.executable,
                "-m",
                "procrastinate",
                "--app=mercury.jobs.cli.app",
                "worker",
                "--queues",
                "mail",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                db.session.remove()
                statuses = [job.status for job in _jobs("mercury:discover_recent_threads")]
                if statuses == ["doing"]:
                    break
                time.sleep(0.25)
            else:
                pytest.fail("worker never picked up the job")
        finally:
            worker.kill()
            worker.wait(timeout=10)
            holder.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": str(account_id)})
            holder.close()

    # Without heartbeats the job is stalled; recovery re-queues it and a new worker finishes it.
    monkeypatch.setattr(task_module, "STALLED_HEARTBEAT_SECONDS", 1)
    time.sleep(1.5)
    worker_app = create_queue_app(app.config["SQLALCHEMY_DATABASE_URI"], worker=True)

    async def recover():
        async with worker_app.open_async():
            await task_module.retry_stalled_jobs(SimpleNamespace(app=worker_app), timestamp=None)

    asyncio.run(recover())
    with app.app_context():
        assert [job.status for job in _jobs("mercury:discover_recent_threads")] == ["todo"]
        db.session.remove()

    _run_one_shot_worker(app)

    with app.app_context():
        assert db.session.get(ProcessingRun, run_id).status == "succeeded"
        assert [job.status for job in _jobs("mercury:discover_recent_threads")] == ["succeeded"]


def test_multiple_queue_apps_keep_stable_task_names(app):
    """Regression: a worker process builds the web enqueue App and the worker App."""
    first = create_queue_app(app.config["SQLALCHEMY_DATABASE_URI"])
    second = create_queue_app(app.config["SQLALCHEMY_DATABASE_URI"], worker=True)
    expected = {
        "mercury:discover_recent_threads",
        "mercury:sync_account_history",
        "mercury:apply_owned_label",
        "mercury:reconcile_pending_work",
        "mercury:retry_stalled_jobs",
        "mercury:renew_gmail_watches",
    }
    for queue_app in (first, second, app.extensions["mercury"]["queue"]):
        ours = {name: task for name, task in queue_app.tasks.items() if "mercury" in name}
        assert set(ours) == expected
        assert all(task.name == name for name, task in ours.items())
    periodic = {name for name, _periodic_id in second.periodic_registry.periodic_tasks}
    assert periodic == {
        "mercury:reconcile_pending_work",
        "mercury:retry_stalled_jobs",
        "mercury:renew_gmail_watches",
    }


def test_manual_refresh_reuses_active_run_instead_of_queueing_another(
    app, client, connected, monkeypatch
):
    monkeypatch.setitem(app.config, "MAIL_MODE", "gmail")
    token = csrf_token(client.get("/app"))
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        existing = _new_run(account, status="running")
        existing_id = existing.id

    response = client.post("/app/sync", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/app/runs/{existing_id}")
    with app.app_context():
        active = db.session.scalars(
            select(ProcessingRun).where(ProcessingRun.status.in_(("pending", "running")))
        ).all()
        assert [run.id for run in active] == [existing_id]
        assert _jobs("mercury:discover_recent_threads") == []


def test_manual_refresh_queues_a_new_run_once_the_previous_one_finished(
    app, client, connected, monkeypatch
):
    monkeypatch.setitem(app.config, "MAIL_MODE", "gmail")
    token = csrf_token(client.get("/app"))
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        _new_run(account, status="failed")

    response = client.post("/app/sync", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        # The fixture mailbox has a history checkpoint, so Sync applies only what changed.
        assert _jobs("mercury:discover_recent_threads") == []
        [job] = _jobs("mercury:sync_account_history")
        run = db.session.scalar(select(ProcessingRun).where(ProcessingRun.kind == "sync"))
        assert job.status == "todo"
        assert job.args["run_id"] == str(run.id)


def test_full_rebuild_relists_the_mailbox_and_is_hidden_in_production(
    app, client, connected, monkeypatch
):
    monkeypatch.setitem(app.config, "MAIL_MODE", "gmail")
    token = csrf_token(client.get("/app"))

    response = client.post("/app/sync/full", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        [job] = _jobs("mercury:discover_recent_threads")
        assert job.status == "todo"
        assert _jobs("mercury:sync_account_history") == []
    monkeypatch.setitem(app.config, "APP_ENV", "production")
    assert client.post("/app/sync/full", data={"csrf_token": token}).status_code == 404


def test_reconcile_resumes_incremental_runs_incrementally(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = _new_run(account)
        run.kind = "sync"
        db.session.commit()

        counts = reconcile(app)

        assert (counts["sync"], counts["discovery"]) == (1, 0)
        [job] = _jobs("mercury:sync_account_history")
        assert job.args["run_id"] == str(run.id)
