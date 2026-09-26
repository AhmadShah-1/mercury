from __future__ import annotations

import math

from flask import current_app
from sqlalchemy import select

from mercury.extensions import db
from mercury.inbox.models import EmailThread, ThreadAnalysis, ThreadEmbedding
from mercury.inbox.reader import build_thread_view
from mercury.inbox.service import mail_provider_for
from mercury.intelligence.prompts import NORMALIZATION_VERSION, SUMMARY_PROMPT_VERSION


def ai_provider():
    return current_app.extensions["mercury"]["ai_provider"]


def _analysis_text(thread: EmailThread, provider_thread) -> tuple[str, tuple[str, ...]]:
    view = build_thread_view(
        provider_thread,
        max_bytes=min(current_app.config["MAX_READER_BYTES"], 48_000),
        max_messages=min(current_app.config["MAX_THREAD_MESSAGES"], 8),
    )
    chunks = [f"Subject: {thread.subject}"]
    ids: list[str] = []
    for message in reversed(view.messages):
        ids.append(message.id)
        chunks.append(
            f"Message-ID: {message.id}\n"
            f"From: {message.sender_name} <{message.sender_address}>\n"
            f"{message.text}"
        )
    return "\n\n---\n\n".join(chunks)[:24_000], tuple(ids)


def analyze_thread(thread: EmailThread) -> None:
    account = db.session.get(
        __import__("mercury.accounts.models", fromlist=["GmailAccount"]).GmailAccount,
        thread.gmail_account_id,
    )
    if account is None or account.connection_state != "connected":
        return
    provider_thread = mail_provider_for(account).get_thread(thread.gmail_thread_id)
    text, message_ids = _analysis_text(thread, provider_thread)
    provider = ai_provider()
    result = provider.summarize(text=text, message_ids=message_ids)
    vector, _ = provider.embed(text[:6_000])
    if len(vector) != 512 or not all(math.isfinite(value) for value in vector):
        raise ValueError("invalid_embedding")
    analysis = db.session.scalar(
        select(ThreadAnalysis).where(ThreadAnalysis.thread_id == thread.id)
    )
    if analysis is None:
        analysis = ThreadAnalysis(
            thread_id=thread.id,
            user_id=thread.user_id,
            summary=result.summary,
            model=current_app.config["SUMMARY_MODEL"],
            prompt_version=SUMMARY_PROMPT_VERSION,
            content_version=thread.content_version,
        )
        db.session.add(analysis)
    analysis.summary = result.summary
    analysis.action_required = result.action_required
    analysis.action_type = result.action_type
    analysis.action_text = result.action_text
    analysis.due_date = result.due_date
    analysis.source_message_id = result.source_message_id
    analysis.uncertain = result.uncertain
    analysis.content_version = thread.content_version
    analysis.stale = False
    embedding = db.session.scalar(
        select(ThreadEmbedding).where(ThreadEmbedding.thread_id == thread.id)
    )
    if embedding is None:
        embedding = ThreadEmbedding(
            thread_id=thread.id,
            user_id=thread.user_id,
            embedding=vector,
            provider=provider.name,
            model=current_app.config["EMBEDDING_MODEL"],
            dimensions=512,
            pipeline_version=NORMALIZATION_VERSION,
            content_version=thread.content_version,
        )
        db.session.add(embedding)
    else:
        embedding.embedding = vector
        embedding.provider = provider.name
        embedding.model = current_app.config["EMBEDDING_MODEL"]
        embedding.content_version = thread.content_version
    thread.processing_state = "complete"
    db.session.commit()


def analyze_pending(user_id) -> None:
    threads = db.session.scalars(
        select(EmailThread)
        .where(EmailThread.user_id == user_id, EmailThread.processing_state == "pending")
        .order_by(EmailThread.latest_message_at.desc())
        .limit(100)
    ).all()
    for thread in threads:
        analyze_thread(thread)
