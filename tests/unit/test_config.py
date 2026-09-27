from __future__ import annotations

import base64

import pytest

from mercury.config import ConfigError, load_config


def _production_env() -> dict[str, str]:
    return {
        "APP_ENV": "production",
        "APP_BASE_URL": "https://mercury.example",
        "DATABASE_URL": (
            "postgresql+psycopg://mercury:secret@db.example/mercury?sslmode=verify-full"
        ),
        "SECRET_KEY": "s" * 48,
        "TOKEN_ENCRYPTION_KEYS": base64.urlsafe_b64encode(b"k" * 32).decode(),
        "AUTH_MODE": "google",
        "MAIL_MODE": "gmail",
        "AI_PROVIDER": "openai",
        "SYNC_MODE": "poll",
        "GOOGLE_CLIENT_ID": "client",
        "GOOGLE_CLIENT_SECRET": "secret",
        "OPENAI_API_KEY": "key",
        "SUPPORT_EMAIL": "support@example.invalid",
        "AI_SUMMARY_INPUT_USD_PER_MILLION": "1",
        "AI_SUMMARY_OUTPUT_USD_PER_MILLION": "1",
        "AI_EMBEDDING_INPUT_USD_PER_MILLION": "1",
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [("AUTH_MODE", "dev"), ("MAIL_MODE", "fake"), ("AI_PROVIDER", "fake")],
)
def test_production_rejects_synthetic_providers(name, value):
    environment = _production_env()
    environment[name] = value
    with pytest.raises(ConfigError):
        load_config(environ=environment)


def test_production_requires_operator_supplied_ai_rates():
    environment = _production_env()
    del environment["AI_SUMMARY_INPUT_USD_PER_MILLION"]
    with pytest.raises(ConfigError, match="AI_SUMMARY_INPUT"):
        load_config(environ=environment)


def test_dev_login_requires_loopback_origin():
    with pytest.raises(ConfigError, match="loopback"):
        load_config(
            environ={
                "APP_ENV": "development",
                "APP_BASE_URL": "https://demo.example",
                "AUTH_MODE": "dev",
            }
        )


def test_azure_openai_endpoint_is_accepted_and_named_on_consent_pages():
    environment = _production_env()
    environment["OPENAI_BASE_URL"] = "https://mercury-openai.openai.azure.com/openai/v1/"
    config = load_config(environ=environment)
    assert config["OPENAI_BASE_URL"] == "https://mercury-openai.openai.azure.com/openai/v1"
    assert config["AI_PROCESSOR_NAME"] == "Azure OpenAI (Microsoft)"


def test_blank_openai_endpoint_uses_the_openai_api():
    environment = _production_env()
    environment["OPENAI_BASE_URL"] = ""
    config = load_config(environ=environment)
    assert config["OPENAI_BASE_URL"] == "https://api.openai.com/v1"
    assert config["AI_PROCESSOR_NAME"] == "OpenAI"


@pytest.mark.parametrize(
    "url",
    [
        "http://mercury-openai.openai.azure.com/openai/v1",
        "https://collector.example/openai/v1",
        "https://evilopenai.azure.com/openai/v1",
        "https://user:pass@mercury-openai.openai.azure.com/openai/v1",
    ],
)
def test_openai_endpoint_rejects_unapproved_destinations(url):
    environment = _production_env()
    environment["OPENAI_BASE_URL"] = url
    with pytest.raises(ConfigError, match="OPENAI_BASE_URL"):
        load_config(environ=environment)
