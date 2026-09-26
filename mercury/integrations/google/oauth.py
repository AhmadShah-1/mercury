from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from flask import current_app, request, session
from sqlalchemy import select

from mercury.accounts.models import GmailAccount, OAuthAttempt, User
from mercury.extensions import db, oauth

OIDC_SCOPES = "openid email profile"
GMAIL_READ_SCOPES = "openid email profile https://www.googleapis.com/auth/gmail.readonly"
GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"


def register_google_client(app) -> None:
    if app.config["GOOGLE_CLIENT_ID"]:
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": OIDC_SCOPES},
        )


def _safe_return_path(value: str | None) -> str:
    if not value:
        return "/app"
    target = urlsplit(value)
    if target.scheme or target.netloc or not value.startswith("/") or value.startswith("//"):
        return "/app"
    return value[:255]


def start_flow(*, purpose: str, user: User | None, gmail_modify: bool = False):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    nonce = secrets.token_urlsafe(24)
    browser_id = session.setdefault("browser_session_id", secrets.token_urlsafe(24))
    cipher = current_app.extensions["mercury"]["token_cipher"]
    attempt = OAuthAttempt(
        user_id=user.id if user else None,
        browser_session_id=browser_id,
        purpose=purpose,
        state_digest=hashlib.sha256(state.encode()).hexdigest(),
        nonce=nonce,
        encrypted_verifier=cipher.encrypt({"verifier": verifier}),
        return_path=_safe_return_path(request.form.get("next")),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.session.add(attempt)
    db.session.commit()
    session["google_oauth_purpose"] = purpose
    scopes = GMAIL_READ_SCOPES + (" " + GMAIL_MODIFY_SCOPE if gmail_modify else "")
    redirect_uri = (
        current_app.config["GOOGLE_LOGIN_REDIRECT_URI"]
        if purpose in {"login", "reauth"}
        else current_app.config["GOOGLE_GMAIL_REDIRECT_URI"]
    )
    kwargs = {
        "redirect_uri": redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": OIDC_SCOPES if purpose in {"login", "reauth"} else scopes,
    }
    if purpose not in {"login", "reauth"}:
        kwargs.update(access_type="offline", include_granted_scopes="true", prompt="consent")
    return oauth.google.authorize_redirect(**kwargs)


def consume_attempt(*, purpose: str) -> OAuthAttempt:
    state = request.args.get("state", "")
    digest = hashlib.sha256(state.encode()).hexdigest()
    attempt = db.session.scalar(select(OAuthAttempt).where(OAuthAttempt.state_digest == digest))
    browser_id = session.get("browser_session_id")
    now = datetime.now(UTC)
    if (
        attempt is None
        or attempt.purpose != purpose
        or attempt.browser_session_id != browser_id
        or attempt.consumed_at is not None
        or attempt.expires_at < now
    ):
        raise ValueError("invalid_oauth_state")
    attempt.consumed_at = now
    db.session.commit()
    return attempt


def exchange_token(attempt: OAuthAttempt) -> dict:
    cipher = current_app.extensions["mercury"]["token_cipher"]
    verifier = cipher.decrypt(attempt.encrypted_verifier)["verifier"]
    return oauth.google.authorize_access_token(code_verifier=verifier, nonce=attempt.nonce)


def user_from_identity(token: dict) -> User:
    claims = token.get("userinfo") or oauth.google.parse_id_token(token)
    if not claims.get("sub") or not claims.get("email_verified"):
        raise ValueError("invalid_google_identity")
    user = db.session.scalar(select(User).where(User.google_subject == claims["sub"]))
    if user is None:
        user = User(
            google_subject=claims["sub"],
            email=claims["email"].lower(),
            display_name=(claims.get("name") or claims["email"])[:120],
        )
        db.session.add(user)
        db.session.commit()
    return user


def connect_google_account(user: User, token: dict) -> GmailAccount:
    claims = token.get("userinfo") or oauth.google.parse_id_token(token)
    if claims.get("sub") != user.google_subject:
        raise ValueError("wrong_google_account")
    scopes = set((token.get("scope") or "").split())
    if "https://www.googleapis.com/auth/gmail.readonly" not in scopes:
        raise ValueError("missing_gmail_scope")
    account = db.session.scalar(select(GmailAccount).where(GmailAccount.user_id == user.id))
    cipher = current_app.extensions["mercury"]["token_cipher"]
    if account is None:
        account = GmailAccount(
            user_id=user.id,
            provider_subject=claims["sub"],
            mailbox_address=claims["email"].lower(),
            granted_scopes=sorted(scopes),
            encrypted_token_bundle=cipher.encrypt(token),
            ai_consent=True,
            disclosure_version="2026-09-v1",
        )
        db.session.add(account)
    else:
        old = (
            cipher.decrypt(account.encrypted_token_bundle) if account.encrypted_token_bundle else {}
        )
        if not token.get("refresh_token") and old.get("refresh_token"):
            token["refresh_token"] = old["refresh_token"]
        account.encrypted_token_bundle = cipher.encrypt(token)
        account.granted_scopes = sorted(scopes)
        account.connection_state = "connected"
        account.connection_generation += 1
    db.session.commit()
    return account
