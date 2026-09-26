from __future__ import annotations

import uuid
from datetime import UTC, datetime

from flask import current_app
from sqlalchemy import delete, select

from mercury.accounts.models import GmailAccount, SecurityAuditEvent, User
from mercury.extensions import db

DEMO_SUBJECT = "mercury-synthetic-user"


def get_or_create_demo_user(email: str = "alex@example.invalid") -> User:
    if current_app.config["AUTH_MODE"] != "dev" or current_app.config["APP_ENV"] == "production":
        raise PermissionError("development login is disabled")
    user = db.session.scalar(select(User).where(User.google_subject == DEMO_SUBJECT))
    if user is None:
        user = User(google_subject=DEMO_SUBJECT, email=email.lower(), display_name="Alex Mercury")
        db.session.add(user)
        db.session.commit()
    return user


def connect_fake_mailbox(user: User, *, ai_consent: bool) -> GmailAccount:
    if current_app.config["MAIL_MODE"] != "fake" or current_app.config["APP_ENV"] == "production":
        raise PermissionError("synthetic mailbox is disabled")
    account = db.session.scalar(select(GmailAccount).where(GmailAccount.user_id == user.id))
    if account is None:
        profile = current_app.extensions["mercury"]["mail_provider"](None).profile()
        account = GmailAccount(
            user_id=user.id,
            provider_subject=profile.subject,
            mailbox_address=profile.email,
            granted_scopes=["fixture:gmail.readonly"],
            ai_consent=ai_consent,
            disclosure_version="2026-09-v1",
        )
        db.session.add(account)
    else:
        account.connection_state = "connected"
        account.ai_consent = ai_consent
        account.connection_generation += 1
    db.session.commit()
    return account


def disconnect_account(user: User) -> None:
    account = db.session.scalar(select(GmailAccount).where(GmailAccount.user_id == user.id))
    if account is None:
        return
    account.connection_state = "deleting"
    account.connection_generation += 1
    account.encrypted_token_bundle = None
    db.session.flush()
    db.session.delete(account)
    db.session.add(
        SecurityAuditEvent(
            event_type="gmail_disconnected",
            actor_id=user.id,
            resource_id=account.id,
            outcome="success",
        )
    )
    user.session_generation = uuid.uuid4()
    db.session.commit()


def delete_user_account(user: User) -> None:
    user_id = user.id
    user.active = False
    user.deletion_requested_at = datetime.now(UTC)
    if user.gmail_account:
        user.gmail_account.connection_state = "deleting"
        user.gmail_account.connection_generation += 1
        user.gmail_account.encrypted_token_bundle = None
    db.session.flush()
    db.session.execute(delete(User).where(User.id == user_id))
    db.session.add(
        SecurityAuditEvent(
            event_type="account_deleted", actor_id=user_id, resource_id=user_id, outcome="success"
        )
    )
    db.session.commit()
