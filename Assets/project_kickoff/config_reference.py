"""Mercury configuration reference: adapt into mercury/config.py.

Load once inside create_app(), after Doppler injects environment variables.
No SDK calls, secret downloads, or environment reads happen at import time.
Only this module reads deployment environment variables.

Accounts needed: Google Cloud, OpenAI, Doppler, Azure, and GitHub.
The app never needs a Google service-account private key for ordinary Gmail
OAuth or for verifying an authenticated Pub/Sub push.

This is a configuration scaffold, not an implementation of the security
middleware, token encryption, provider adapters, or worker described in the spec.
"""
from __future__ import annotations

import base64
import os
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit


class ConfigError(ValueError):
    """Safe to show at startup: messages name settings, never secret values."""


DEV_SECRET = "mercury-local-fixtures-only-not-a-production-secret"
DEV_TOKEN_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()


def load_config(
    overrides: Mapping[str, Any] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a fresh config for each Flask app instance, then validate it."""
    env = dict(os.environ if environ is None else environ)

    def text(name: str, default: str = "") -> str:
        return env.get(name, default).strip()

    def flag(name: str, default: bool) -> bool:
        value = text(name, "true" if default else "false").lower()
        if value not in {"true", "false", "1", "0", "yes", "no"}:
            raise ConfigError(f"{name} must be true or false")
        return value in {"true", "1", "yes"}

    def integer(name: str, default: int, low: int, high: int) -> int:
        try:
            value = int(text(name, str(default)))
        except ValueError as exc:
            raise ConfigError(f"{name} must be an integer") from exc
        if not low <= value <= high:
            raise ConfigError(f"{name} is outside its allowed range")
        return value

    def money(name: str, default: str) -> Decimal:
        try:
            value = Decimal(text(name, default))
        except InvalidOperation as exc:
            raise ConfigError(f"{name} must be a decimal amount") from exc
        if not value.is_finite() or value < 0:
            raise ConfigError(f"{name} must be finite and non-negative")
        return value

    # CORE: Set APP_ENV explicitly in Doppler; never infer production from DEBUG.
    # Local app: http://localhost:5000. Production: your actual HTTPS domain.
    app_env = text("APP_ENV")
    if app_env not in {"development", "testing", "production"}:
        raise ConfigError("APP_ENV must be development, testing, or production")
    production = app_env == "production"
    base_url = text("APP_BASE_URL", "" if production else "http://localhost:5000")
    base_url = base_url.rstrip("/")
    host = urlsplit(base_url).hostname
    extra_hosts = [v.strip() for v in text("ADDITIONAL_TRUSTED_HOSTS").split(",") if v.strip()]

    # SECRETS: Generate locally and save directly in Doppler's selected config.
    # SECRET_KEY: python -c "import secrets; print(secrets.token_hex(32))"
    # TOKEN_ENCRYPTION_KEYS: poetry run python -c \
    #   "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # For rotation, list newest first, then old keys, separated by commas.
    # Do not use the demo defaults with real Gmail data, even in development.
    secret = text("SECRET_KEY", "" if production else DEV_SECRET)
    token_keys = tuple(v.strip() for v in text(
        "TOKEN_ENCRYPTION_KEYS", "" if production else DEV_TOKEN_KEY
    ).split(",") if v.strip())

    # DATABASE: Local Compose injects its own container hostname URL.
    # Azure: portal.azure.com -> PostgreSQL flexible server -> connection details.
    # Production example (replace values, URL-encode password):
    # postgresql+psycopg://USER:PASSWORD@HOST:5432/mercury?sslmode=verify-full&sslrootcert=/etc/ssl/certs/ca-certificates.crt
    # The queue DSN is derived centrally from this URL, not a second DB service.
    database_url = text("DATABASE_URL", "" if production else
        "postgresql+psycopg://mercury:mercury_local@localhost:5433/mercury")

    # GOOGLE: console.cloud.google.com -> Google Auth Platform -> Clients.
    # Create a Web application OAuth client in a separate dev/prod project.
    # Register BOTH derived callback URLs below exactly. Enable Gmail API.
    # No client secret may be sent to the browser.
    auth_mode = text("AUTH_MODE", "google" if production else "dev")
    mail_mode = text("MAIL_MODE", "gmail" if production else "fake")
    project = text("GOOGLE_PROJECT_ID")

    # AI: platform.openai.com -> project -> API keys and usage/billing controls.
    # Keep one provider initially. Fake mode needs no key and no network.
    # Model changes require evaluation; embedding changes require re-indexing.
    ai_provider = text("AI_PROVIDER", "openai" if production else "fake")

    # PUB/SUB: same Google project -> Pub/Sub -> topic + authenticated push
    # subscription. Use a dedicated push identity, not a downloaded JSON key.
    # Audience must exactly match what the subscription puts in its OIDC JWT.
    # Local manual/poll mode needs none of these Pub/Sub settings.
    sync_mode = text("SYNC_MODE", "push" if production else "manual")

    config: dict[str, Any] = {
        "APP_ENV": app_env,
        "APP_BASE_URL": base_url,
        "RELEASE_ID": text("RELEASE_ID", "development"),
        "SUPPORT_EMAIL": text("SUPPORT_EMAIL"),
        "DEBUG": flag("DEBUG", False),
        "TESTING": app_env == "testing",
        "SECRET_KEY": secret,
        "TOKEN_ENCRYPTION_KEYS": token_keys,
        "SQLALCHEMY_DATABASE_URI": database_url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "pool_pre_ping": True, "pool_size": 2, "max_overflow": 1,
            "pool_timeout": 10, "pool_recycle": 300,
            "connect_args": {"connect_timeout": 5},
        },
        "AUTH_MODE": auth_mode,
        "MAIL_MODE": mail_mode,
        "GOOGLE_CLIENT_ID": text("GOOGLE_CLIENT_ID"),
        "GOOGLE_CLIENT_SECRET": text("GOOGLE_CLIENT_SECRET"),
        "GOOGLE_LOGIN_REDIRECT_URI": base_url + "/auth/google/callback",
        "GOOGLE_GMAIL_REDIRECT_URI": base_url + "/auth/gmail/callback",
        "GOOGLE_PROJECT_ID": project,
        "GMAIL_LABEL_WRITES_ENABLED": flag("GMAIL_LABEL_WRITES_ENABLED", False),
        "GMAIL_LABEL_PREFIX": "Mercury",
        "SYNC_MODE": sync_mode,
        "SYNC_INTERVAL_SECONDS": integer("SYNC_INTERVAL_SECONDS", 300, 60, 3600),
        "PUBSUB_TOPIC": text("PUBSUB_TOPIC", f"projects/{project}/topics/mercury-mailbox-events" if project else ""),
        "PUBSUB_SUBSCRIPTION": text("PUBSUB_SUBSCRIPTION"),
        "PUBSUB_PUSH_SERVICE_ACCOUNT": text("PUBSUB_PUSH_SERVICE_ACCOUNT"),
        "PUBSUB_AUDIENCE": text("PUBSUB_AUDIENCE", base_url + "/webhooks/google/pubsub"),
        "AI_PROVIDER": ai_provider,
        "AI_PROCESSING_ENABLED": flag("AI_PROCESSING_ENABLED", True),
        "OPENAI_API_KEY": text("OPENAI_API_KEY"),
        "SUMMARY_MODEL": text("SUMMARY_MODEL", "gpt-4.1-mini"),
        "EMBEDDING_MODEL": text("EMBEDDING_MODEL", "text-embedding-3-small"),
        "EMBEDDING_DIMENSIONS": 512,  # Schema/pipeline contract, not a casual env toggle.
        "AI_GLOBAL_MONTHLY_BUDGET_USD": money("AI_GLOBAL_MONTHLY_BUDGET_USD", "50"),
        "AI_ACCOUNT_MONTHLY_BUDGET_USD": money("AI_ACCOUNT_MONTHLY_BUDGET_USD", "3"),
        "AI_ACCOUNT_DAILY_THREAD_LIMIT": integer("AI_ACCOUNT_DAILY_THREAD_LIMIT", 100, 1, 1000),
        "INDEX_MAX_THREADS": integer("INDEX_MAX_THREADS", 2000, 1, 5000),
        "INDEX_LOOKBACK_DAYS": integer("INDEX_LOOKBACK_DAYS", 180, 1, 365),
        "SUMMARY_LOOKBACK_DAYS": 30,
        "SUMMARY_MAX_INPUT_TOKENS": 3000,
        "SUMMARY_MAX_OUTPUT_TOKENS": 220,
        "EMBEDDING_MAX_INPUT_TOKENS": 800,
        "INDEX_BATCH_SIZE": 25,
        "MAX_THREAD_MESSAGES": 20,
        "MAX_READER_BYTES": 2 * 1024 * 1024,
        "MAX_MIME_DEPTH": 12,
        "PROVIDER_TIMEOUT_SECONDS": integer("PROVIDER_TIMEOUT_SECONDS", 20, 5, 60),
        "WORKER_CONCURRENCY": integer("WORKER_CONCURRENCY", 2, 1, 4),
        "LOG_LEVEL": text("LOG_LEVEL", "INFO"),
        # PROXY_HOPS: set only after verifying the actual Azure ingress chain.
        "PROXY_HOPS": integer("PROXY_HOPS", 0, 0, 2),
        "TRUSTED_HOSTS": list(dict.fromkeys(([host] if host else []) + extra_hosts)),
        # Security defaults are code-level invariants, not production off-switches.
        "SESSION_COOKIE_NAME": "__Host-mercury" if production else "mercury-dev",
        "SESSION_COOKIE_SECURE": production,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_DOMAIN": None,
        "SESSION_COOKIE_PATH": "/",
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
        "SESSION_REFRESH_EACH_REQUEST": False,
        "WTF_CSRF_ENABLED": True,
        "WTF_CSRF_TIME_LIMIT": timedelta(hours=1),
        "MAX_CONTENT_LENGTH": 256 * 1024,
        "MAX_FORM_MEMORY_SIZE": 64 * 1024,
        "MAX_FORM_PARTS": 100,
    }
    if overrides:
        config.update(overrides)
    validate_config(config)
    return config


def validate_config(config: Mapping[str, Any]) -> None:
    """Fail early on unsafe combinations without printing credentials."""
    def require(*names: str) -> None:
        for name in names:
            if not config.get(name):
                raise ConfigError(f"{name} is required for the selected mode")

    env = config["APP_ENV"]
    if env not in {"development", "testing", "production"}:
        raise ConfigError("APP_ENV is invalid")
    if config["AUTH_MODE"] not in {"dev", "google"}:
        raise ConfigError("AUTH_MODE is invalid")
    if config["MAIL_MODE"] not in {"fake", "gmail"}:
        raise ConfigError("MAIL_MODE is invalid")
    if config["AI_PROVIDER"] not in {"fake", "openai"}:
        raise ConfigError("AI_PROVIDER is invalid")
    if config["SYNC_MODE"] not in {"manual", "poll", "push"}:
        raise ConfigError("SYNC_MODE is invalid")
    require("SECRET_KEY", "SQLALCHEMY_DATABASE_URI", "TOKEN_ENCRYPTION_KEYS")
    if len(config["SECRET_KEY"]) < 32:
        raise ConfigError("SECRET_KEY must contain at least 32 characters")
    try:
        keys = config["TOKEN_ENCRYPTION_KEYS"]
        if isinstance(keys, str) or not all(
            len(base64.b64decode(k.encode(), altchars=b"-_", validate=True)) == 32
            for k in keys
        ):
            raise ValueError
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ConfigError("TOKEN_ENCRYPTION_KEYS must contain valid Fernet keys") from exc

    origin = urlsplit(config["APP_BASE_URL"])
    if (origin.scheme not in {"http", "https"} or not origin.hostname
            or origin.username or origin.password or origin.query
            or origin.fragment or origin.path):
        raise ConfigError("APP_BASE_URL must be a plain HTTP(S) origin")
    if any("*" in host or "/" in host for host in config["TRUSTED_HOSTS"]):
        raise ConfigError("TRUSTED_HOSTS must contain explicit hostnames")
    if origin.hostname not in config["TRUSTED_HOSTS"]:
        raise ConfigError("TRUSTED_HOSTS must include the configured application host")
    for callback in ("GOOGLE_LOGIN_REDIRECT_URI", "GOOGLE_GMAIL_REDIRECT_URI"):
        target = urlsplit(config[callback])
        if (target.scheme, target.netloc) != (origin.scheme, origin.netloc):
            raise ConfigError(f"{callback} must use APP_BASE_URL")
    db_url = urlsplit(config["SQLALCHEMY_DATABASE_URI"])
    if db_url.scheme != "postgresql+psycopg" or not db_url.hostname:
        raise ConfigError("DATABASE_URL must use postgresql+psycopg")

    if config["AUTH_MODE"] == "google" or config["MAIL_MODE"] == "gmail":
        require("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
    if config["MAIL_MODE"] == "gmail":
        if config["AUTH_MODE"] != "google":
            raise ConfigError("Real Gmail requires Google authentication")
        if config["SECRET_KEY"] == DEV_SECRET or DEV_TOKEN_KEY in config["TOKEN_ENCRYPTION_KEYS"]:
            raise ConfigError("Real Gmail requires non-demo session and encryption keys")
    if config["AI_PROVIDER"] == "openai" and config["AI_PROCESSING_ENABLED"]:
        require("OPENAI_API_KEY", "SUMMARY_MODEL", "EMBEDDING_MODEL")
    if config["SYNC_MODE"] == "push":
        if config["MAIL_MODE"] != "gmail":
            raise ConfigError("Push mode requires real Gmail")
        require("GOOGLE_PROJECT_ID", "PUBSUB_TOPIC", "PUBSUB_SUBSCRIPTION",
                "PUBSUB_PUSH_SERVICE_ACCOUNT", "PUBSUB_AUDIENCE")
        prefix = f"projects/{config['GOOGLE_PROJECT_ID']}/"
        if not config["PUBSUB_TOPIC"].startswith(prefix + "topics/"):
            raise ConfigError("PUBSUB_TOPIC must belong to GOOGLE_PROJECT_ID")
        if not config["PUBSUB_SUBSCRIPTION"].startswith(prefix + "subscriptions/"):
            raise ConfigError("PUBSUB_SUBSCRIPTION must belong to GOOGLE_PROJECT_ID")
    if env == "testing" and (config["MAIL_MODE"] != "fake" or config["AI_PROVIDER"] != "fake"):
        raise ConfigError("Default test mode forbids live Gmail and AI providers")
    if config["AUTH_MODE"] == "dev" and origin.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ConfigError("Development login requires a loopback application origin")
    if env == "production":
        if config["DEBUG"] or config["TESTING"]:
            raise ConfigError("Production forbids DEBUG and TESTING")
        if (config["AUTH_MODE"], config["MAIL_MODE"], config["AI_PROVIDER"]) != ("google", "gmail", "openai"):
            raise ConfigError("Production forbids development providers")
        if origin.scheme != "https" or origin.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ConfigError("Production requires a non-loopback HTTPS origin")
        if config["SYNC_MODE"] == "manual":
            raise ConfigError("Production requires poll or push synchronization")
        if parse_qs(db_url.query).get("sslmode") != ["verify-full"]:
            raise ConfigError("Production DATABASE_URL requires sslmode=verify-full")
        require("SUPPORT_EMAIL")
        if (not config["SESSION_COOKIE_SECURE"] or not config["SESSION_COOKIE_HTTPONLY"]
                or not config["WTF_CSRF_ENABLED"]
                or config["SESSION_COOKIE_DOMAIN"] is not None
                or config["SESSION_COOKIE_PATH"] != "/"
                or config["SESSION_COOKIE_NAME"] != "__Host-mercury"
                or config["SESSION_COOKIE_SAMESITE"] != "Lax"):
            raise ConfigError("Production session/CSRF settings cannot be weakened")

# DOPPLER_TOKEN is intentionally absent from Flask config. It bootstraps
# `doppler run -- <process>` in production and belongs in an Azure secret.
# Never log it or use a personal Doppler token in a production container.
