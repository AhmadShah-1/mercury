from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mercury.accounts.models import utcnow
from mercury.extensions import db


class EmailThread(db.Model):
    __tablename__ = "email_threads"
    __table_args__ = (
        UniqueConstraint("gmail_account_id", "gmail_thread_id", name="uq_thread_provider_id"),
        UniqueConstraint("id", "user_id", name="uq_thread_owner"),
        UniqueConstraint("id", "user_id", "gmail_account_id", name="uq_thread_owner_account"),
        ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_thread_account_owner",
            ondelete="CASCADE",
        ),
        Index("ix_thread_owner_latest", "user_id", "latest_message_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    gmail_thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    subject: Mapped[str] = mapped_column(String(998), nullable=False, default="(no subject)")
    participants: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False, default=list)
    snippet: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    latest_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gmail_unread: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attachment_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    content_version: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    last_indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageReference(db.Model):
    __tablename__ = "message_references"
    __table_args__ = (
        UniqueConstraint("gmail_account_id", "gmail_message_id", name="uq_message_provider_id"),
        ForeignKeyConstraint(
            ["thread_id", "user_id", "gmail_account_id"],
            ["email_threads.id", "email_threads.user_id", "email_threads.gmail_account_id"],
            name="fk_message_thread_owner",
            ondelete="CASCADE",
        ),
        Index("ix_message_thread_time", "thread_id", "sent_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    gmail_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    internet_message_id: Mapped[str | None] = mapped_column(String(998))
    sender_name: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    sender_address: Mapped[str] = mapped_column(String(320), nullable=False)
    recipients: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gmail_labels: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    attachment_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ThreadAnalysis(db.Model):
    __tablename__ = "thread_analyses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["thread_id", "user_id"],
            ["email_threads.id", "email_threads.user_id"],
            name="fk_analysis_thread_owner",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(700), nullable=False)
    action_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    action_type: Mapped[str] = mapped_column(String(24), nullable=False, default="none")
    action_text: Mapped[str | None] = mapped_column(String(500))
    due_date: Mapped[Date | None] = mapped_column(Date)
    source_message_id: Mapped[str | None] = mapped_column(String(128))
    uncertain: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_version: Mapped[str] = mapped_column(String(64), nullable=False)
    action_status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ThreadEmbedding(db.Model):
    __tablename__ = "thread_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["thread_id", "user_id"],
            ["email_threads.id", "email_threads.user_id"],
            name="fk_embedding_thread_owner",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    embedding: Mapped[list[float]] = mapped_column(VECTOR(512), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(nullable=False, default=512)
    pipeline_version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessingRun(db.Model):
    __tablename__ = "processing_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_run_account_owner",
            ondelete="CASCADE",
        ),
        Index("ix_run_owner_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    found_count: Mapped[int] = mapped_column(nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(nullable=False, default=0)
    requested_limit: Mapped[int] = mapped_column(nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
