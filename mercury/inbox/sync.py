"""Checkpointed Gmail history synchronization and enqueue-gap reconciliation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache

from flask import current_app
from googleapiclient.errors import HttpError
from sqlalchemy import URL, Engine, create_engine, select, text
from sqlalchemy.pool import NullPool

from mercury.accounts.models import GmailAccount
from mercury.extensions import db
from mercury.inbox.models import ProcessingRun
from mercury.inbox.service import index_account, mail_provider_for, upsert_provider_thread


@lru_cache(maxsize=4)
def _lock_engine(url: URL) -> Engine:
    # Unpooled: closing a lock connection must end its database session, which is what
    # releases a session-level advisory lock, instead of parking it in the pool. Autocommit
    # keeps the connection from idling inside a transaction for the length of a job.
    return create_engine(
        url, poolclass=NullPool, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5}
    )


@contextmanager
def account_lock(account_id):
    """Serialize one account's mailbox work across worker threads and processes.

    Advisory locks belong to a database session, but ORM commits hand ``db.session``'s
    connection back to the pool, so an unlock issued through it can reach a different session
    and leak the lock. The lock therefore lives on its own connection for the whole block.
    """
    key = str(account_id)
    with _lock_engine(db.engine.url).connect() as lock_connection:
        lock_connection.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": key})
        try:
            yield
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise


def _history_thread_ids(page: dict) -> set[str]:
    found: set[str] = set()
    for record in page.get("history", []):
        for key in ("messagesAdded", "messagesDeleted", "labelsAdded", "labelsRemoved"):
            for change in record.get(key, []):
                message = change.get("message", {})
                if message.get("threadId"):
                    found.add(str(message["threadId"]))
    return found


def sync_account_history(
    account_id, connection_generation: int, run_id=None, *, finalize: bool = True
) -> None:
    """Apply Gmail history since the checkpoint; ``finalize=False`` leaves a supplied run open.

    Runs this function creates itself (checkpoint recovery) are always finalized here.
    """
    with account_lock(account_id):
        account = db.session.scalar(
            select(GmailAccount).where(GmailAccount.id == account_id).with_for_update()
        )
        if (
            account is None
            or account.connection_state != "connected"
            or account.connection_generation != connection_generation
        ):
            return
        run = db.session.get(ProcessingRun, run_id) if run_id else None
        provider = mail_provider_for(account)
        if not account.last_history_id:
            if run is None:
                finalize = True
                run = ProcessingRun(
                    user_id=account.user_id,
                    gmail_account_id=account.id,
                    kind="recovery",
                    requested_limit=current_app.config["INDEX_MAX_THREADS"],
                )
                db.session.add(run)
                db.session.commit()
            index_account(account, run, limit=run.requested_limit, finalize=finalize)
            return

        page_token = None
        changed_ids: set[str] = set()
        newest_history_id = account.last_history_id
        try:
            while True:
                page = provider.list_history(account.last_history_id, page_token=page_token)
                changed_ids.update(_history_thread_ids(page))
                newest_history_id = str(page.get("historyId") or newest_history_id)
                page_token = page.get("nextPageToken")
                if not page_token:
                    break
        except HttpError as error:
            if getattr(error.resp, "status", None) != 404:
                raise
            recovery = run or ProcessingRun(
                user_id=account.user_id,
                gmail_account_id=account.id,
                kind="checkpoint-recovery",
                requested_limit=current_app.config["INDEX_MAX_THREADS"],
            )
            if run is None:
                finalize = True
                db.session.add(recovery)
                db.session.commit()
            index_account(account, recovery, limit=recovery.requested_limit, finalize=finalize)
            return

        if len(changed_ids) > current_app.config["INDEX_MAX_THREADS"]:
            raise ValueError("history_change_limit_exceeded")
        if run:
            run.stage = "synchronizing"
            run.status = "running"
            run.found_count = len(changed_ids)
            db.session.commit()
        for provider_thread_id in sorted(changed_ids):
            db.session.refresh(account)
            if (
                account.connection_generation != connection_generation
                or account.connection_state != "connected"
            ):
                return
            try:
                provider_thread = provider.get_thread_metadata(provider_thread_id)
            except LookupError:
                continue
            upsert_provider_thread(account, provider_thread)
            if run:
                run.completed_count += 1
            db.session.commit()

        db.session.refresh(account)
        if account.connection_generation != connection_generation:
            return
        account.last_history_id = newest_history_id
        account.pending_sync = False
        account.last_synced_at = datetime.now(UTC)
        if run and finalize:
            run.stage = "complete"
            run.status = "succeeded"
            run.finished_at = datetime.now(UTC)
        elif run:
            run.stage = "analyzing"
        db.session.commit()
