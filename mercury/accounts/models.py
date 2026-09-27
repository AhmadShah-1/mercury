from __future__ import annotations

import uuid
from datetime import UTC, datetime

from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mercury.extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    google_subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    session_generation: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    gmail_account: Mapped[GmailAccount | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )

    @property
    def is_active(self) -> bool:
        return self.active

    def get_id(self) -> str:
        return str(self.id)


class GmailAccount(db.Model):
    __tablename__ = "gmail_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_gmail_account_user"),
        UniqueConstraint("id", "user_id", name="uq_gmail_account_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    mailbox_address: Mapped[str] = mapped_column(String(320), nullable=False)
    encrypted_token_bundle: Mapped[str | None] = mapped_column(Text)
    granted_scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    connection_state: Mapped[str] = mapped_column(String(32), nullable=False, default="connected")
    connection_generation: Mapped[int] = mapped_column(nullable=False, default=1)
    last_history_id: Mapped[str | None] = mapped_column(String(64))
    pending_sync: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    watch_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last time automatic organization changed a placement or bucket; drives live refresh hints.
    last_organized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label_write_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disclosure_version: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="gmail_account")


class OAuthAttempt(db.Model):
    __tablename__ = "oauth_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    browser_session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    state_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_verifier: Mapped[str] = mapped_column(Text, nullable=False)
    return_path: Mapped[str] = mapped_column(String(255), nullable=False, default="/app")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityAuditEvent(db.Model):
    __tablename__ = "security_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
