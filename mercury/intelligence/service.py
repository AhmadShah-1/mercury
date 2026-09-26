from __future__ import annotations

import math

from flask import current_app
from sqlalchemy import select

from mercury.accounts.models import GmailAccount
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ThreadAnalysis, ThreadEmbedding
from mercury.inbox.reader import build_thread_view
from mercury.inbox.service import mail_provider_for
from mercury.intelligence.budget import (
    BudgetExceeded,
    cancel_reservation,
    finish_reservation,
    reserve_analysis,
)
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


def analyze_thread(thread: EmailThread, *, onboarding: bool = False) -> None:
    account = db.session.get(GmailAccount, thread.gmail_account_id)
    if account is None or account.connection_state != "connected" or not account.ai_consent:
        return
    generation = account.connection_generation
    content_version = thread.content_version
    provider_thread = mail_provider_for(account).get_thread(thread.gmail_thread_id)
    text, message_ids = _analysis_text(thread, provider_thread)
    try:
        usage = reserve_analysis(
            user_id=thread.user_id,
            thread_id=thread.id,
            estimated_input_tokens=max(1, len(text) // 4),
            estimated_output_tokens=current_app.config["SUMMARY_MAX_OUTPUT_TOKENS"],
            estimated_embedding_tokens=max(1, min(len(text), 6_000) // 4),
            quota_category="analysis-onboarding" if onboarding else "analysis-daily",
        )
    except BudgetExceeded:
        thread.processing_state = "budget_paused"
        db.session.commit()
        return
    provider = ai_provider()
    try:
        result = provider.summarize(text=text, message_ids=message_ids)
        vector, embedding_tokens = provider.embed(text[:6_000])
    except Exception:
        cancel_reservation(usage.id)
        raise
    if len(vector) != 512 or not all(math.isfinite(value) for value in vector):
        cancel_reservation(usage.id)
        raise ValueError("invalid_embedding")
    db.session.expire_all()
    account = db.session.get(GmailAccount, thread.gmail_account_id)
    current_thread = db.session.get(EmailThread, thread.id)
    if (
        account is None
        or current_thread is None
        or account.connection_generation != generation
        or account.connection_state != "connected"
        or current_thread.content_version != content_version
    ):
        cancel_reservation(usage.id, status="stale")
        return
    thread = current_thread
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
    finish_reservation(
        usage.id,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        embedding_tokens=embedding_tokens,
    )


def analyze_pending(user_id, *, onboarding: bool = False) -> None:
    threads = db.session.scalars(
        select(EmailThread)
        .where(EmailThread.user_id == user_id, EmailThread.processing_state == "pending")
        .order_by(EmailThread.latest_message_at.desc())
        .limit(100)
    ).all()
    for thread in threads:
        analyze_thread(thread, onboarding=onboarding)
