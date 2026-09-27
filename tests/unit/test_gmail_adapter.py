"""Gmail adapter credential lifecycle and error translation, with Google calls mocked.

All token strings are invented fixtures.
"""

# ruff: noqa: S105, S106, S107

from __future__ import annotations

import time
from types import SimpleNamespace

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError
from sqlalchemy import select

from mercury.accounts.models import GmailAccount
from mercury.extensions import db
from mercury.integrations.google.gmail import GmailProvider
from mercury.integrations.types import ProviderUnavailable, ReauthorizationRequired

SCOPES = ["openid", "https://www.googleapis.com/auth/gmail.readonly"]


def _store_bundle(app, *, access_token="old-access", expires_in=-3600, refresh="refresh-1"):
    cipher = app.extensions["mercury"]["token_cipher"]
    account = db.session.scalar(select(GmailAccount))
    account.encrypted_token_bundle = cipher.encrypt(
        {
            "access_token": access_token,
            "refresh_token": refresh,
            "expires_at": int(time.time()) + expires_in,
        }
    )
    account.granted_scopes = SCOPES
    db.session.commit()
    return account


def _stored(app, account):
    db.session.refresh(account)
    return app.extensions["mercury"]["token_cipher"].decrypt(account.encrypted_token_bundle)


def test_invalid_grant_requires_reconnect_without_retry(app, connected, monkeypatch):
    def invalid_grant(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(Credentials, "refresh", invalid_grant)
    with app.app_context():
        account = _store_bundle(app)
        provider = GmailProvider(account)
        with pytest.raises(ReauthorizationRequired):
            provider.profile()
        db.session.refresh(account)
        assert account.connection_state == "reconnect_required"
        assert _stored(app, account)["refresh_token"] == "refresh-1"


def test_retryable_refresh_failure_is_transient(app, connected, monkeypatch):
    def unavailable(self, request):
        raise RefreshError("temporarily unavailable", retryable=True)

    monkeypatch.setattr(Credentials, "refresh", unavailable)
    with app.app_context():
        account = _store_bundle(app)
        with pytest.raises(ProviderUnavailable):
            GmailProvider(account).profile()
        db.session.refresh(account)
        assert account.connection_state == "connected"


def test_refresh_preserves_refresh_token_omitted_by_google(app, connected, monkeypatch):
    calls = []

    def refreshed(self, request):
        calls.append(1)
        self.token = "new-access"
        self.expiry = Credentials(token="x").expiry
        self._refresh_token = None  # Google may omit refresh_token on refresh responses.

    monkeypatch.setattr(Credentials, "refresh", refreshed)
    with app.app_context():
        account = _store_bundle(app)
        provider = GmailProvider(account)
        provider._persist_refresh()
        bundle = _stored(app, account)
        assert calls == [1]
        assert bundle["access_token"] == "new-access"
        assert bundle["refresh_token"] == "refresh-1"
        assert "new-access" not in (account.encrypted_token_bundle or "")


def test_concurrent_refresh_reuses_token_stored_by_other_process(app, connected, monkeypatch):
    def must_not_refresh(self, request):
        raise AssertionError("refresh should be skipped when a valid token is already stored")

    with app.app_context():
        account = _store_bundle(app)
        provider = GmailProvider(account)  # In-memory credentials are expired.
        # Another worker refreshed while this one waited for the row lock.
        _store_bundle(app, access_token="refreshed-elsewhere", expires_in=3600)
        monkeypatch.setattr(Credentials, "refresh", must_not_refresh)
        provider._persist_refresh()
        assert provider.credentials.token == "refreshed-elsewhere"


def test_missing_refresh_token_requires_reconnect(app, connected):
    with app.app_context():
        account = _store_bundle(app, refresh=None)
        with pytest.raises(ReauthorizationRequired):
            GmailProvider(account).profile()


def test_service_uses_finite_timeout(app, connected):
    with app.app_context():
        provider = GmailProvider(_store_bundle(app, expires_in=3600))
        assert provider.service._http.http.timeout == app.config["PROVIDER_TIMEOUT_SECONDS"]


class _Request:
    def __init__(self, error):
        self.error = error

    def execute(self, num_retries=0):
        raise self.error


def _http_error(status, *, content=b"provider body", **headers):
    return HttpError(httplib2.Response({"status": str(status), **headers}), content)


@pytest.mark.parametrize(
    ("error", "expected", "code"),
    [
        (_http_error(404), LookupError, "provider_resource_not_found"),
        (_http_error(401), ReauthorizationRequired, "connection_needs_reauthorization"),
        (_http_error(429, **{"retry-after": "7"}), ProviderUnavailable, "provider_rate_limited"),
        (_http_error(503), ProviderUnavailable, "provider_unavailable"),
        (TimeoutError(), ProviderUnavailable, "provider_timeout"),
    ],
)
def test_execute_translates_provider_errors_to_safe_types(error, expected, code):
    with pytest.raises(expected) as caught:
        GmailProvider._execute(_Request(error))
    assert str(caught.value) == code
    assert "provider body" not in str(caught.value)
    if code == "provider_rate_limited":
        assert caught.value.retry_after == 7


def test_history_404_is_left_for_checkpoint_recovery():
    with pytest.raises(HttpError):
        GmailProvider._execute(_Request(_http_error(404)), translate_not_found=False)


def test_execute_translates_google_403_rate_limit_to_bounded_retry():
    error = _http_error(
        403,
        content=(
            b'{"error":{"errors":[{"domain":"usageLimits",'
            b'"reason":"rateLimitExceeded","message":"quota body"}]}}'
        ),
    )

    with pytest.raises(ProviderUnavailable) as caught:
        GmailProvider._execute(_Request(error))

    assert str(caught.value) == "provider_rate_limited"
    assert caught.value.retry_after == 60
    assert "quota body" not in str(caught.value)


def test_execute_does_not_retry_unrelated_403():
    error = _http_error(
        403,
        content=b'{"error":{"errors":[{"reason":"domainPolicy"}]}}',
    )

    with pytest.raises(HttpError):
        GmailProvider._execute(_Request(error))


def test_discovery_stops_at_limit_without_requesting_a_zero_sized_page():
    list_calls = []

    class StaticRequest:
        def __init__(self, response):
            self.response = response

        def execute(self, num_retries=0):
            return self.response

    class Threads:
        def list(self, **kwargs):
            list_calls.append(kwargs)
            return StaticRequest(
                {
                    "threads": [{"id": "thread-1"}],
                    "resultSizeEstimate": 2,
                    "nextPageToken": "must-not-be-used",
                }
            )

        def get(self, **kwargs):
            return StaticRequest(
                {
                    "id": kwargs["id"],
                    "messages": [
                        {
                            "id": "message-1",
                            "internalDate": "0",
                            "labelIds": [],
                            "payload": {"headers": []},
                        }
                    ],
                }
            )

    threads = Threads()
    provider = object.__new__(GmailProvider)
    provider.credentials = SimpleNamespace(valid=True)
    provider.service = SimpleNamespace(users=lambda: SimpleNamespace(threads=lambda: threads))
    provider._discovery_quota_ready_at = time.monotonic()
    provider._pace_discovery = lambda _units: None

    discovery = provider.list_threads(limit=1, after_epoch=0)

    assert len(list(discovery.threads)) == 1
    assert len(list_calls) == 1
    assert list_calls[0]["maxResults"] == 1


def test_account_without_stored_credentials_asks_for_reconnection(app, connected):
    # The synthetic mailbox has no token bundle; in Gmail mode it must stop being scheduled.
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        assert not account.encrypted_token_bundle
        with pytest.raises(ReauthorizationRequired):
            GmailProvider(account)
        db.session.refresh(account)
        assert account.connection_state == "reconnect_required"


def test_undecryptable_credentials_fail_closed_without_forcing_reconnection(app, connected):
    from mercury.security.crypto import TokenDecryptionError

    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        account.encrypted_token_bundle = "written-with-a-different-key"
        db.session.commit()
        with pytest.raises(TokenDecryptionError):
            GmailProvider(account)
        db.session.refresh(account)
        assert account.connection_state == "connected"
