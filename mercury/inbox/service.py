from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime

from flask import current_app
from sqlalchemy import select

from mercury.accounts.models import GmailAccount, User
from mercury.extensions import db
from mercury.inbox.models import EmailThread, MessageReference, ProcessingRun
from mercury.integrations.types import MailProvider, ProviderThread


def mail_provider_for(account: GmailAccount) -> MailProvider:
    return current_app.extensions["mercury"]["mail_provider"](account)


def _version(thread: ProviderThread) -> str:
    material = "|".join(
        f"{message.id}:{message.sent_at.isoformat()}"
        for message in thread.messages
        if not message.is_draft
    )
    return hashlib.sha256(("reader-v1|" + material).encode()).hexdigest()


def index_account(account: GmailAccount, run: ProcessingRun, *, limit: int) -> None:
    if account.connection_state != "connected":
        raise ValueError("connection_needs_reauthorization")
    provider = mail_provider_for(account)
    cutoff = int(time.time()) - current_app.config["INDEX_LOOKBACK_DAYS"] * 86400
    threads = provider.list_threads(limit=limit, after_epoch=cutoff)
    run.stage = "indexing"
    run.status = "running"
    run.found_count = len(threads)
    db.session.commit()

    for provider_thread in threads:
        existing = db.session.scalar(
            select(EmailThread).where(
                EmailThread.gmail_account_id == account.id,
                EmailThread.gmail_thread_id == provider_thread.id,
            )
        )
        messages = [message for message in provider_thread.messages if not message.is_draft]
        if not messages:
            continue
        latest = max(message.sent_at for message in messages)
        participants = [
            {"name": message.sender_name, "address": message.sender_address}
            for message in messages[-5:]
        ]
        thread = existing or EmailThread(
            user_id=account.user_id,
            gmail_account_id=account.id,
            gmail_thread_id=provider_thread.id,
            latest_message_at=latest,
            content_version=_version(provider_thread),
        )
        thread.subject = provider_thread.subject[:998] or "(no subject)"
        thread.participants = participants
        thread.snippet = provider_thread.snippet[:500]
        thread.latest_message_at = latest
        thread.gmail_unread = provider_thread.unread
        thread.attachment_present = any(message.attachment_present for message in messages)
        thread.content_version = _version(provider_thread)
        thread.processing_state = "pending"
        thread.last_indexed_at = datetime.now(UTC)
        if existing is None:
            db.session.add(thread)
            db.session.flush()
        for message in messages:
            reference = db.session.scalar(
                select(MessageReference).where(
                    MessageReference.gmail_account_id == account.id,
                    MessageReference.gmail_message_id == message.id,
                )
            )
            if reference is None:
                db.session.add(
                    MessageReference(
                        user_id=account.user_id,
                        gmail_account_id=account.id,
                        thread_id=thread.id,
                        gmail_message_id=message.id,
                        internet_message_id=message.internet_message_id,
                        sender_name=message.sender_name[:320],
                        sender_address=message.sender_address[:320],
                        recipients=list(message.recipients),
                        sent_at=message.sent_at,
                        gmail_labels=list(message.labels),
                        attachment_present=message.attachment_present,
                    )
                )
        run.completed_count += 1
        db.session.commit()
    account.last_synced_at = datetime.now(UTC)
    account.last_history_id = provider.profile().history_id
    account.pending_sync = False
    run.stage = "complete"
    run.status = "succeeded"
    run.finished_at = datetime.now(UTC)
    db.session.commit()


def create_run(user: User, account: GmailAccount, *, kind: str, limit: int) -> ProcessingRun:
    run = ProcessingRun(
        user_id=user.id,
        gmail_account_id=account.id,
        kind=kind,
        requested_limit=min(limit, current_app.config["INDEX_MAX_THREADS"]),
    )
    db.session.add(run)
    db.session.commit()
    return run


def owned_thread(user_id: uuid.UUID, thread_id: uuid.UUID) -> EmailThread | None:
    return db.session.scalar(
        select(EmailThread).where(EmailThread.id == thread_id, EmailThread.user_id == user_id)
    )


def owned_run(user_id: uuid.UUID, run_id: uuid.UUID) -> ProcessingRun | None:
    return db.session.scalar(
        select(ProcessingRun).where(ProcessingRun.id == run_id, ProcessingRun.user_id == user_id)
    )
