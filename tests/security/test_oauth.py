from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from mercury.accounts.models import GmailAccount, OAuthAttempt, User
from mercury.extensions import db
from mercury.integrations.google.oauth import (
    GMAIL_READ_SCOPES,
    _safe_return_path,
    connect_google_account,
    consume_attempt,
)


def test_external_and_scheme_relative_return_urls_are_rejected():
    assert _safe_return_path("https://attacker.invalid/steal") == "/app"
    assert _safe_return_path("//attacker.invalid/steal") == "/app"
    assert _safe_return_path("/app/buckets") == "/app/buckets"


def test_oauth_state_is_single_use_and_bound_to_browser_session(app):
    state = secrets.token_urlsafe(20)
    with app.app_context():
        cipher = app.extensions["mercury"]["token_cipher"]
        db.session.add(
            OAuthAttempt(
                browser_session_id="browser-a",
                purpose="login",
                state_digest=hashlib.sha256(state.encode()).hexdigest(),
                nonce="nonce",
                encrypted_verifier=cipher.encrypt({"verifier": "verifier"}),
                return_path="/app",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        db.session.commit()

        with app.test_request_context(f"/auth/google/callback?state={state}"):
            from flask import session

            session["browser_session_id"] = "browser-a"
            consume_attempt(purpose="login")
        with app.test_request_context(f"/auth/google/callback?state={state}"):
            from flask import session

            session["browser_session_id"] = "browser-a"
            with pytest.raises(ValueError, match="invalid_oauth_state"):
                consume_attempt(purpose="login")


def test_reconnect_preserves_refresh_token_and_rejects_wrong_subject(app):
    with app.app_context():
        user = User(
            google_subject="google-subject",
            email="user@example.invalid",
            display_name="User",
        )
        db.session.add(user)
        db.session.flush()
        cipher = app.extensions["mercury"]["token_cipher"]
        account = GmailAccount(
            user_id=user.id,
            provider_subject=user.google_subject,
            mailbox_address=user.email,
            granted_scopes=GMAIL_READ_SCOPES.split(),
            encrypted_token_bundle=cipher.encrypt(
                {"access_token": "old-access", "refresh_token": "old-refresh"}
            ),
        )
        db.session.add(account)
        db.session.commit()

        token = {
            "access_token": "new-access",
            "scope": GMAIL_READ_SCOPES,
            "userinfo": {
                "sub": user.google_subject,
                "email": user.email,
                "email_verified": True,
            },
        }
        connect_google_account(user, token)
        db.session.refresh(account)
        decrypted = cipher.decrypt(account.encrypted_token_bundle)
        assert decrypted["refresh_token"] == "old-refresh"  # noqa: S105 - invented fixture
        assert "old-refresh" not in account.encrypted_token_bundle

        wrong = dict(token, userinfo={"sub": "other-subject", "email": user.email})
        with pytest.raises(ValueError, match="wrong_google_account"):
            connect_google_account(user, wrong)


def test_partial_gmail_scope_is_rejected(app):
    with app.app_context():
        user = User(
            google_subject="partial-subject",
            email="partial@example.invalid",
            display_name="Partial",
        )
        db.session.add(user)
        db.session.commit()
        with pytest.raises(ValueError, match="missing_gmail_scope"):
            connect_google_account(
                user,
                {
                    "access_token": "token",
                    "scope": "openid email",
                    "userinfo": {
                        "sub": user.google_subject,
                        "email": user.email,
                        "email_verified": True,
                    },
                },
            )
        assert db.session.scalar(select(GmailAccount)) is None
