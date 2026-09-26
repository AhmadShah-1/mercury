from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from mercury.accounts.models import utcnow
from mercury.extensions import db


class UsageBucket(db.Model):
    __tablename__ = "usage_buckets"
    __table_args__ = (
        UniqueConstraint("subject_key", "category", "window_start", name="uq_usage_window"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    subject_key: Mapped[str] = mapped_column(String(96), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    operation_count: Mapped[int] = mapped_column(nullable=False, default=0)


class AIUsage(db.Model):
    __tablename__ = "ai_usage"
    __table_args__ = (
        ForeignKeyConstraint(
            ["thread_id", "user_id"],
            ["email_threads.id", "email_threads.user_id"],
            name="fk_ai_usage_thread_owner",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    embedding_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    input_rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    output_rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    embedding_rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    actual_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="reserved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
