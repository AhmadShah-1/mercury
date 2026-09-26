from __future__ import annotations

import hashlib
import time
import uuid
from datetime import UTC, datetime

from flask import current_app
from sqlalchemy import delete, select

from mercury.accounts.models import GmailAccount, User
from mercury.extensions import db
from mercury.inbox.models import EmailThread, MessageReference, ProcessingRun, ThreadAnalysis
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


def upsert_provider_thread(account: GmailAccount, provider_thread: ProviderThread) -> bool:
    """Persist bounded metadata and return whether message content/membership changed."""
    existing = db.session.scalar(
        select(EmailThread).where(
            EmailThread.gmail_account_id == account.id,
            EmailThread.gmail_thread_id == provider_thread.id,
        )
    )
    messages = [message for message in provider_thread.messages if not message.is_draft]
    if not messages:
        return False
    version = _version(provider_thread)
    content_changed = existing is None or existing.content_version != version
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
        content_version=version,
    )
    thread.subject = provider_thread.subject[:998] or "(no subject)"
    thread.participants = participants
    thread.snippet = provider_thread.snippet[:500]
    thread.latest_message_at = latest
    thread.gmail_unread = provider_thread.unread
    thread.attachment_present = any(message.attachment_present for message in messages)
    thread.content_version = version
    if content_changed:
        thread.processing_state = "pending"
    thread.last_indexed_at = datetime.now(UTC)
    if existing is None:
        db.session.add(thread)
        db.session.flush()
    elif content_changed:
        analysis = db.session.scalar(
            select(ThreadAnalysis).where(ThreadAnalysis.thread_id == thread.id)
        )
        if analysis:
            analysis.stale = True

    message_ids = {message.id for message in messages}
    references = {
        item.gmail_message_id: item
        for item in db.session.scalars(
            select(MessageReference).where(MessageReference.thread_id == thread.id)
        )
    }
    for message in messages:
        reference = references.get(message.id)
        if reference is None:
            reference = MessageReference(
                user_id=account.user_id,
                gmail_account_id=account.id,
                thread_id=thread.id,
                gmail_message_id=message.id,
            )
            db.session.add(reference)
        reference.internet_message_id = message.internet_message_id
        reference.sender_name = message.sender_name[:320]
        reference.sender_address = message.sender_address[:320]
        reference.recipients = list(message.recipients)
        reference.sent_at = message.sent_at
        reference.gmail_labels = list(message.labels)
        reference.attachment_present = message.attachment_present
    removed_ids = [item.id for key, item in references.items() if key not in message_ids]
    if removed_ids:
        db.session.execute(delete(MessageReference).where(MessageReference.id.in_(removed_ids)))
    from mercury.buckets.service import apply_sender_rule

    apply_sender_rule(
        user_id=account.user_id,
        account_id=account.id,
        thread=thread,
        sender=messages[-1].sender_address,
    )
    return content_changed


def index_account(account: GmailAccount, run: ProcessingRun, *, limit: int) -> None:
    if account.connection_state != "connected":
        raise ValueError("connection_needs_reauthorization")
    provider = mail_provider_for(account)
    generation = account.connection_generation
    cutoff = int(time.time()) - current_app.config["INDEX_LOOKBACK_DAYS"] * 86400
    threads = provider.list_threads(limit=limit, after_epoch=cutoff)
    db.session.refresh(account)
    if account.connection_generation != generation or account.connection_state != "connected":
        return
    run.stage = "indexing"
    run.status = "running"
    run.found_count = len(threads)
    db.session.commit()

    for provider_thread in threads:
        db.session.refresh(account)
        if account.connection_generation != generation or account.connection_state != "connected":
            return
        upsert_provider_thread(account, provider_thread)
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
