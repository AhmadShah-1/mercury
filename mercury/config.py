"""Environment-backed configuration loaded only from the application factory."""

from __future__ import annotations

import base64
import os
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlsplit


class ConfigError(ValueError):
    """A startup-safe configuration error that never contains a secret value."""


DEV_SECRET = "mercury-local-fixtures-only-not-a-production-secret"  # noqa: S105  # nosec B105
DEV_TOKEN_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()


def load_config(
    overrides: Mapping[str, Any] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
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

    def similarity(name: str, default: float) -> float:
        try:
            value = float(text(name, str(default)))
        except ValueError as exc:
            raise ConfigError(f"{name} must be a number") from exc
        if not 0.0 <= value <= 1.0:
            raise ConfigError(f"{name} must be between 0 and 1")
        return value

    def money(name: str, default: str = "") -> Decimal | None:
        raw = text(name, default)
        if not raw:
            return None
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise ConfigError(f"{name} must be a decimal amount") from exc
        if not value.is_finite() or value < 0:
            raise ConfigError(f"{name} must be finite and non-negative")
        return value

    app_env = text("APP_ENV")
    if app_env not in {"development", "testing", "production"}:
        raise ConfigError("APP_ENV must be development, testing, or production")
    production = app_env == "production"
    base_url = text("APP_BASE_URL", "" if production else "http://localhost:5000").rstrip("/")
    host = urlsplit(base_url).hostname
    extra_hosts = [v.strip() for v in text("ADDITIONAL_TRUSTED_HOSTS").split(",") if v.strip()]
    project = text("GOOGLE_PROJECT_ID")

    config: dict[str, Any] = {
        "APP_ENV": app_env,
        "APP_BASE_URL": base_url,
        "RELEASE_ID": text("RELEASE_ID", "development"),
        "SUPPORT_EMAIL": text("SUPPORT_EMAIL"),
        "DEBUG": flag("DEBUG", False),
        "TESTING": app_env == "testing",
        "SECRET_KEY": text("SECRET_KEY", "" if production else DEV_SECRET),
        "TOKEN_ENCRYPTION_KEYS": tuple(
            value.strip()
            for value in text("TOKEN_ENCRYPTION_KEYS", "" if production else DEV_TOKEN_KEY).split(
                ","
            )
            if value.strip()
        ),
        "SQLALCHEMY_DATABASE_URI": text(
            "DATABASE_URL",
            ""
            if production
            else "postgresql+psycopg://mercury:mercury_local@localhost:5433/mercury",
        ),
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "pool_pre_ping": True,
            "pool_size": 2,
            "max_overflow": 1,
            "pool_timeout": 10,
            "pool_recycle": 300,
            "connect_args": {"connect_timeout": 5},
        },
        "AUTH_MODE": text("AUTH_MODE", "google" if production else "dev"),
        "MAIL_MODE": text("MAIL_MODE", "gmail" if production else "fake"),
        "GOOGLE_CLIENT_ID": text("GOOGLE_CLIENT_ID"),
        "GOOGLE_CLIENT_SECRET": text("GOOGLE_CLIENT_SECRET"),
        "GOOGLE_LOGIN_REDIRECT_URI": base_url + "/auth/google/callback",
        "GOOGLE_GMAIL_REDIRECT_URI": base_url + "/auth/gmail/callback",
        "GOOGLE_PROJECT_ID": project,
        "GMAIL_LABEL_WRITES_ENABLED": flag("GMAIL_LABEL_WRITES_ENABLED", False),
        "GMAIL_LABEL_PREFIX": "Mercury",
        "SYNC_MODE": text("SYNC_MODE", "push" if production else "manual"),
        "SYNC_INTERVAL_SECONDS": integer("SYNC_INTERVAL_SECONDS", 300, 60, 3600),
        "PUBSUB_TOPIC": text(
            "PUBSUB_TOPIC",
            f"projects/{project}/topics/mercury-mailbox-events" if project else "",
        ),
        "PUBSUB_SUBSCRIPTION": text("PUBSUB_SUBSCRIPTION"),
        "PUBSUB_PUSH_SERVICE_ACCOUNT": text("PUBSUB_PUSH_SERVICE_ACCOUNT"),
        "PUBSUB_AUDIENCE": text("PUBSUB_AUDIENCE", base_url + "/webhooks/google/pubsub"),
        "AI_PROVIDER": text("AI_PROVIDER", "openai" if production else "fake"),
        "AI_PROCESSING_ENABLED": flag("AI_PROCESSING_ENABLED", True),
        "OPENAI_API_KEY": text("OPENAI_API_KEY"),
        "SUMMARY_MODEL": text("SUMMARY_MODEL", "gpt-4.1-mini-2025-04-14"),
        "EMBEDDING_MODEL": text("EMBEDDING_MODEL", "text-embedding-3-small"),
        "EMBEDDING_DIMENSIONS": 512,
        "AI_SUMMARY_INPUT_USD_PER_MILLION": money("AI_SUMMARY_INPUT_USD_PER_MILLION"),
        "AI_SUMMARY_OUTPUT_USD_PER_MILLION": money("AI_SUMMARY_OUTPUT_USD_PER_MILLION"),
        "AI_EMBEDDING_INPUT_USD_PER_MILLION": money("AI_EMBEDDING_INPUT_USD_PER_MILLION"),
        "AI_GLOBAL_MONTHLY_BUDGET_USD": money("AI_GLOBAL_MONTHLY_BUDGET_USD", "50"),
        "AI_ACCOUNT_MONTHLY_BUDGET_USD": money("AI_ACCOUNT_MONTHLY_BUDGET_USD", "3"),
        # Thread-count caps may reach INDEX_MAX_THREADS' ceiling so any indexed window can be
        # analyzed; the monthly USD budgets above remain the hard spending limit.
        "AI_ACCOUNT_DAILY_THREAD_LIMIT": integer("AI_ACCOUNT_DAILY_THREAD_LIMIT", 100, 1, 5000),
        "AI_ONBOARDING_THREAD_LIMIT": integer("AI_ONBOARDING_THREAD_LIMIT", 500, 1, 5000),
        "MAX_SUGGESTED_BUCKETS": integer("MAX_SUGGESTED_BUCKETS", 12, 1, 24),
        "MAX_ACTIVE_BUCKETS": integer("MAX_ACTIVE_BUCKETS", 30, 1, 100),
        # Cosine thresholds on the mean of a thread's nearest bucket members, measured on one
        # 100-thread development mailbox (512-dimension text-embedding-3-small): at these
        # values clear misfits leave and no unrelated mail is filed. Promotional mail sits
        # around 0.55-0.62 against every bucket, so lower bars misfile it. Re-measure with
        # `flask bucket-scores` on more data before treating them as product constants.
        "BUCKET_MATCH_MIN": similarity("BUCKET_MATCH_MIN", 0.66),
        "BUCKET_MATCH_MARGIN": similarity("BUCKET_MATCH_MARGIN", 0.05),
        "BUCKET_KEEP_MIN": similarity("BUCKET_KEEP_MIN", 0.64),
        "BUCKET_SPLIT_MAX_SIMILARITY": similarity("BUCKET_SPLIT_MAX_SIMILARITY", 0.75),
        "INDEX_MAX_THREADS": integer("INDEX_MAX_THREADS", 2000, 1, 5000),
        "INDEX_LOOKBACK_DAYS": integer("INDEX_LOOKBACK_DAYS", 180, 1, 365),
        # Conversations per workspace list page; older ones load on request, never all at once.
        "INBOX_PAGE_SIZE": integer("INBOX_PAGE_SIZE", 100, 25, 500),
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
        "PROXY_HOPS": integer("PROXY_HOPS", 0, 0, 2),
        "TRUSTED_HOSTS": list(dict.fromkeys(([host] if host else []) + extra_hosts)),
        "SESSION_COOKIE_NAME": "__Host-mercury" if production else "mercury-dev",
        "SESSION_COOKIE_SECURE": production,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_DOMAIN": None,
        "SESSION_COOKIE_PATH": "/",
        "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
        "SESSION_REFRESH_EACH_REQUEST": False,
        "WTF_CSRF_ENABLED": True,
        # Flask-WTF passes this value directly to itsdangerous, which expects seconds.
        "WTF_CSRF_TIME_LIMIT": 3600,
        "MAX_CONTENT_LENGTH": 256 * 1024,
        "MAX_FORM_MEMORY_SIZE": 64 * 1024,
        "MAX_FORM_PARTS": 100,
    }
    if overrides:
        config.update(overrides)
    validate_config(config)
    return config


def validate_config(config: Mapping[str, Any]) -> None:
    def require(*names: str) -> None:
        for name in names:
            if not config.get(name):
                raise ConfigError(f"{name} is required for the selected mode")

    env = config["APP_ENV"]
    if config["AUTH_MODE"] not in {"dev", "google"}:
        raise ConfigError("AUTH_MODE is invalid")
    if config["MAIL_MODE"] not in {"fake", "gmail"}:
        raise ConfigError("MAIL_MODE is invalid")
    if config["AI_PROVIDER"] not in {"fake", "openai"}:
        raise ConfigError("AI_PROVIDER is invalid")
    if config["SYNC_MODE"] not in {"manual", "poll", "push"}:
        raise ConfigError("SYNC_MODE is invalid")
    if config["BUCKET_KEEP_MIN"] > config["BUCKET_MATCH_MIN"]:
        # The keep floor sits below the admit bar so placements do not flip on small changes.
        raise ConfigError("BUCKET_KEEP_MIN must not exceed BUCKET_MATCH_MIN")
    require("SECRET_KEY", "SQLALCHEMY_DATABASE_URI", "TOKEN_ENCRYPTION_KEYS")
    if len(config["SECRET_KEY"]) < 32:
        raise ConfigError("SECRET_KEY must contain at least 32 characters")
    try:
        keys = config["TOKEN_ENCRYPTION_KEYS"]
        if isinstance(keys, str) or not all(
            len(base64.b64decode(key.encode(), altchars=b"-_", validate=True)) == 32 for key in keys
        ):
            raise ValueError
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ConfigError("TOKEN_ENCRYPTION_KEYS must contain valid Fernet keys") from exc

    origin = urlsplit(config["APP_BASE_URL"])
    if (
        origin.scheme not in {"http", "https"}
        or not origin.hostname
        or origin.username
        or origin.password
        or origin.query
        or origin.fragment
        or origin.path
    ):
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
        require(
            "GOOGLE_PROJECT_ID",
            "PUBSUB_TOPIC",
            "PUBSUB_SUBSCRIPTION",
            "PUBSUB_PUSH_SERVICE_ACCOUNT",
            "PUBSUB_AUDIENCE",
        )
        project_prefix = f"projects/{config['GOOGLE_PROJECT_ID']}/"
        if not config["PUBSUB_TOPIC"].startswith(project_prefix + "topics/"):
            raise ConfigError("PUBSUB_TOPIC must belong to GOOGLE_PROJECT_ID")
        if not config["PUBSUB_SUBSCRIPTION"].startswith(project_prefix + "subscriptions/"):
            raise ConfigError("PUBSUB_SUBSCRIPTION must belong to GOOGLE_PROJECT_ID")
    if env == "testing" and (config["MAIL_MODE"] != "fake" or config["AI_PROVIDER"] != "fake"):
        raise ConfigError("Default test mode forbids live Gmail and AI providers")
    if config["AUTH_MODE"] == "dev" and origin.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ConfigError("Development login requires a loopback application origin")
    if env == "production":
        if config["DEBUG"] or config["TESTING"]:
            raise ConfigError("Production forbids DEBUG and TESTING")
        if (config["AUTH_MODE"], config["MAIL_MODE"], config["AI_PROVIDER"]) != (
            "google",
            "gmail",
            "openai",
        ):
            raise ConfigError("Production forbids development providers")
        if origin.scheme != "https" or origin.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ConfigError("Production requires a non-loopback HTTPS origin")
        if config["SYNC_MODE"] == "manual":
            raise ConfigError("Production requires poll or push synchronization")
        if parse_qs(db_url.query).get("sslmode") != ["verify-full"]:
            raise ConfigError("Production DATABASE_URL requires sslmode=verify-full")
        require(
            "SUPPORT_EMAIL",
            "AI_SUMMARY_INPUT_USD_PER_MILLION",
            "AI_SUMMARY_OUTPUT_USD_PER_MILLION",
            "AI_EMBEDDING_INPUT_USD_PER_MILLION",
        )
        if (
            not config["SESSION_COOKIE_SECURE"]
            or not config["SESSION_COOKIE_HTTPONLY"]
            or not config["WTF_CSRF_ENABLED"]
            or config["SESSION_COOKIE_DOMAIN"] is not None
            or config["SESSION_COOKIE_PATH"] != "/"
            or config["SESSION_COOKIE_NAME"] != "__Host-mercury"
            or config["SESSION_COOKIE_SAMESITE"] != "Lax"
        ):
            raise ConfigError("Production session/CSRF settings cannot be weakened")
