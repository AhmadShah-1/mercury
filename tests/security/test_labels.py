from __future__ import annotations

import pytest
from sqlalchemy import select

from mercury.accounts.models import GmailAccount
from mercury.buckets.models import BucketAssignment, GmailLabelMapping
from mercury.extensions import db
from mercury.integrations.google.labels import LabelWriteDenied, apply_owned_label
from mercury.integrations.google.oauth import GMAIL_MODIFY_SCOPE
from tests.conftest import csrf_token


class LabelProvider:
    def __init__(self):
        self.created: list[str] = []
        self.applied: list[tuple[str, list[str], list[str]]] = []

    def create_label(self, name: str) -> str:
        self.created.append(name)
        return "Label_mercury_owned"

    def apply_label(self, thread_id: str, *, add: list[str], remove: list[str]) -> None:
        self.applied.append((thread_id, add, remove))


def test_label_writer_requires_every_runtime_gate(app, connected, monkeypatch):
    provider = LabelProvider()
    monkeypatch.setitem(app.config, "MAIL_MODE", "gmail")
    monkeypatch.setitem(app.config, "GMAIL_LABEL_WRITES_ENABLED", True)
    monkeypatch.setitem(app.extensions["mercury"], "mail_provider", lambda account: provider)
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        assignment = db.session.scalar(
            select(BucketAssignment).where(BucketAssignment.bucket_id.is_not(None))
        )
        account.label_write_consent = True
        account.granted_scopes = [GMAIL_MODIFY_SCOPE]
        db.session.commit()
        apply_owned_label(
            account_id=account.id,
            user_id=account.user_id,
            thread_id=assignment.thread_id,
            bucket_id=assignment.bucket_id,
            connection_generation=account.connection_generation,
        )
        mapping = db.session.scalar(select(GmailLabelMapping))
        assert mapping.gmail_label_id == "Label_mercury_owned"
        assert mapping.sync_status == "synced"
        assert provider.created[0].startswith("Mercury/")
        assert provider.applied[0][1] == ["Label_mercury_owned"]

        with pytest.raises(LabelWriteDenied):
            apply_owned_label(
                account_id=account.id,
                user_id=account.user_id,
                thread_id=assignment.thread_id,
                bucket_id=assignment.bucket_id,
                connection_generation=account.connection_generation - 1,
            )


def test_operator_disabled_label_setting_is_denied_with_csrf(client, connected):
    settings = client.get("/settings")
    response = client.post(
        "/settings/labels",
        data={"enabled": "y", "csrf_token": csrf_token(settings)},
    )
    assert response.status_code == 403


def test_label_setting_without_csrf_is_rejected(client, connected):
    assert client.post("/settings/labels", data={"enabled": "y"}).status_code == 400
