"""Checkpointed Gmail history synchronization and enqueue-gap reconciliation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

from flask import current_app
from googleapiclient.errors import HttpError
from sqlalchemy import select, text

from mercury.accounts.models import GmailAccount
from mercury.extensions import db
from mercury.inbox.models import ProcessingRun
from mercury.inbox.service import index_account, mail_provider_for, upsert_provider_thread


@contextmanager
def account_lock(account_id):
    key = str(account_id)
    db.session.execute(text("SELECT pg_advisory_lock(hashtext(:key))"), {"key": key})
    try:
        yield
    except Exception:
        db.session.rollback()
        raise
    finally:
        db.session.execute(text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": key})
        db.session.commit()


def _history_thread_ids(page: dict) -> set[str]:
    found: set[str] = set()
    for record in page.get("history", []):
        for key in ("messagesAdded", "messagesDeleted", "labelsAdded", "labelsRemoved"):
            for change in record.get(key, []):
                message = change.get("message", {})
                if message.get("threadId"):
                    found.add(str(message["threadId"]))
    return found


def sync_account_history(account_id, connection_generation: int, run_id=None) -> None:
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
                run = ProcessingRun(
                    user_id=account.user_id,
                    gmail_account_id=account.id,
                    kind="recovery",
                    requested_limit=current_app.config["INDEX_MAX_THREADS"],
                )
                db.session.add(run)
                db.session.commit()
            index_account(account, run, limit=run.requested_limit)
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
                db.session.add(recovery)
                db.session.commit()
            index_account(account, recovery, limit=recovery.requested_limit)
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
        if run:
            run.stage = "complete"
            run.status = "succeeded"
            run.finished_at = datetime.now(UTC)
        db.session.commit()
