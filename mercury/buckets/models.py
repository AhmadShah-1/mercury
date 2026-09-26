from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from mercury.accounts.models import utcnow
from mercury.extensions import db


class Bucket(db.Model):
    __tablename__ = "buckets"
    __table_args__ = (
        UniqueConstraint("gmail_account_id", "name", name="uq_bucket_account_name"),
        UniqueConstraint("id", "user_id", "gmail_account_id", name="uq_bucket_owner_account"),
        ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_bucket_account_owner",
            ondelete="CASCADE",
        ),
        Index("ix_bucket_owner_active", "user_id", "archived"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    purpose: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class BucketAssignment(db.Model):
    __tablename__ = "bucket_assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["thread_id", "user_id", "gmail_account_id"],
            ["email_threads.id", "email_threads.user_id", "email_threads.gmail_account_id"],
            name="fk_assignment_thread_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["bucket_id", "user_id", "gmail_account_id"],
            ["buckets.id", "buckets.user_id", "buckets.gmail_account_id"],
            name="fk_assignment_bucket_owner",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    bucket_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False, default="model")
    score: Mapped[float | None]
    locked_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)


class SenderRule(db.Model):
    __tablename__ = "sender_rules"
    __table_args__ = (
        UniqueConstraint("gmail_account_id", "sender_address", name="uq_sender_rule_account"),
        ForeignKeyConstraint(
            ["bucket_id", "user_id", "gmail_account_id"],
            ["buckets.id", "buckets.user_id", "buckets.gmail_account_id"],
            name="fk_sender_rule_bucket_owner",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sender_address: Mapped[str] = mapped_column(String(320), nullable=False)
    bucket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(nullable=False, default=100)


class GmailLabelMapping(db.Model):
    __tablename__ = "gmail_label_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["bucket_id", "user_id", "gmail_account_id"],
            ["buckets.id", "buckets.user_id", "buckets.gmail_account_id"],
            name="fk_label_mapping_bucket_owner",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    gmail_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    bucket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    gmail_label_id: Mapped[str] = mapped_column(String(128), nullable=False)
    desired_name: Mapped[str] = mapped_column(String(225), nullable=False)
    sync_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
