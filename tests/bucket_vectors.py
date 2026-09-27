"""Synthetic, topic-shaped embeddings for bucket tests.

The fake AI provider hashes text into effectively random vectors, so any two threads are
unrelated (cosine ~0). These helpers place threads around chosen topic directions instead:
members of one topic score ~0.8 against each other and ~0 against other topics.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
from flask import current_app
from sqlalchemy import select

from mercury.accounts.models import GmailAccount
from mercury.buckets.models import Bucket, BucketAssignment
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ThreadAnalysis, ThreadEmbedding
from mercury.intelligence.prompts import NORMALIZATION_VERSION, SUMMARY_PROMPT_VERSION


def _unit(values: np.ndarray) -> np.ndarray:
    return values / np.linalg.norm(values)


def topic(seed: int) -> np.ndarray:
    return _unit(np.random.default_rng(seed).standard_normal(512))


def near(direction: np.ndarray, rng: np.random.Generator, spread: float = 0.5) -> list[float]:
    """A member of ``direction``'s topic; ``spread`` 0.5 gives ~0.8 pairwise similarity."""
    return _unit(direction + spread * _unit(rng.standard_normal(512))).tolist()


def add_thread(
    account: GmailAccount,
    vector: list[float],
    *,
    subject: str = "Synthetic topic thread",
    sender: str = "sender@example.invalid",
    received: datetime | None = None,
) -> uuid.UUID:
    """Persist a thread with a current, compatible analysis and embedding."""
    version = uuid.uuid4().hex
    thread = EmailThread(
        user_id=account.user_id,
        gmail_account_id=account.id,
        gmail_thread_id=f"synthetic-{version[:16]}",
        subject=subject,
        participants=[{"name": "Sender", "address": sender}],
        latest_message_at=received or datetime.now(UTC) - timedelta(days=1),
        content_version=version,
        processing_state="complete",
    )
    db.session.add(thread)
    db.session.flush()
    db.session.add(
        ThreadAnalysis(
            thread_id=thread.id,
            user_id=account.user_id,
            summary=f"{subject}. [Synthetic]",
            model=current_app.config["SUMMARY_MODEL"],
            prompt_version=SUMMARY_PROMPT_VERSION,
            content_version=version,
        )
    )
    db.session.add(
        ThreadEmbedding(
            thread_id=thread.id,
            user_id=account.user_id,
            embedding=vector,
            provider=current_app.extensions["mercury"]["ai_provider"].name,
            model=current_app.config["EMBEDDING_MODEL"],
            dimensions=512,
            pipeline_version=NORMALIZATION_VERSION,
            content_version=version,
        )
    )
    db.session.commit()
    return thread.id


def set_vectors(thread_ids: list[uuid.UUID], vectors: list[list[float]]) -> None:
    for thread_id, vector in zip(thread_ids, vectors, strict=True):
        embedding = db.session.scalar(
            select(ThreadEmbedding).where(ThreadEmbedding.thread_id == thread_id)
        )
        embedding.embedding = vector
    db.session.commit()


def make_bucket(account: GmailAccount, name: str, **fields) -> Bucket:
    values = {
        "origin": "suggested",
        "user_confirmed": False,
        "ai_name": name,
        "ai_purpose": f"Synthetic {name.lower()} topic.",
        "ai_named_at": datetime.now(UTC),
    }
    values.update(fields)
    bucket = Bucket(
        user_id=account.user_id,
        gmail_account_id=account.id,
        name=name,
        purpose=values["ai_purpose"],
        **values,
    )
    db.session.add(bucket)
    db.session.commit()
    return bucket


def assign(
    account: GmailAccount, thread_id: uuid.UUID, bucket: Bucket, *, origin: str = "model"
) -> None:
    db.session.add(
        BucketAssignment(
            user_id=account.user_id,
            gmail_account_id=account.id,
            thread_id=thread_id,
            bucket_id=bucket.id,
            origin=origin,
            locked_by_user=origin == "user",
        )
    )
    db.session.commit()


def bucket_of(thread_id: uuid.UUID) -> uuid.UUID | None:
    return db.session.scalar(
        select(BucketAssignment.bucket_id).where(BucketAssignment.thread_id == thread_id)
    )
