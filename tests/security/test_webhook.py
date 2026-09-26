from __future__ import annotations

import base64
import json

from sqlalchemy import select

from mercury.accounts.models import GmailAccount
from mercury.extensions import db


def _envelope(email: str, *, subscription: str = "projects/test/subscriptions/mercury"):
    data = base64.b64encode(
        json.dumps({"emailAddress": email, "historyId": "9007199254740993"}).encode()
    ).decode()
    return {"subscription": subscription, "message": {"data": data}}


def test_pubsub_is_only_csrf_exemption_but_requires_bearer_auth(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "SYNC_MODE", "push")
    response = client.post("/webhooks/google/pubsub", json={})
    assert response.status_code == 401


def test_verified_pubsub_hint_is_durable_and_wrong_subscription_fails(
    app, client, connected, monkeypatch
):
    monkeypatch.setitem(app.config, "SYNC_MODE", "push")
    monkeypatch.setitem(app.config, "PUBSUB_AUDIENCE", "https://mercury.invalid/webhook")
    monkeypatch.setitem(
        app.config, "PUBSUB_PUSH_SERVICE_ACCOUNT", "push@project.iam.gserviceaccount.com"
    )
    monkeypatch.setitem(app.config, "PUBSUB_SUBSCRIPTION", "projects/test/subscriptions/mercury")
    monkeypatch.setattr(
        "mercury.integrations.google.notifications.id_token.verify_oauth2_token",
        lambda token, request, audience: {
            "iss": "https://accounts.google.com",
            "email": "push@project.iam.gserviceaccount.com",
            "email_verified": True,
            "aud": audience,
        },
    )
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        account.pending_sync = False
        email = account.mailbox_address
        account_id = account.id
        db.session.commit()

    accepted = client.post(
        "/webhooks/google/pubsub",
        json=_envelope(email),
        headers={"Authorization": "Bearer signed-fixture"},
    )
    assert accepted.status_code == 202
    with app.app_context():
        assert db.session.get(GmailAccount, account_id).pending_sync is True

    rejected = client.post(
        "/webhooks/google/pubsub",
        json=_envelope(email, subscription="projects/other/subscriptions/wrong"),
        headers={"Authorization": "Bearer signed-fixture"},
    )
    assert rejected.status_code == 400
