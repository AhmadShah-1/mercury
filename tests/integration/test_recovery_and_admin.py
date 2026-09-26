from __future__ import annotations

import httplib2
from googleapiclient.errors import HttpError
from sqlalchemy import select

from mercury.accounts.models import GmailAccount, User
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ProcessingRun, ThreadAnalysis
from mercury.inbox.sync import sync_account_history
from mercury.integrations.fake_gmail import FakeGmailProvider


class ExpiredHistoryProvider(FakeGmailProvider):
    def list_history(self, start_history_id, page_token=None):
        raise HttpError(httplib2.Response({"status": "404"}), b"history expired")


def test_expired_history_checkpoint_triggers_bounded_resync(app, connected, monkeypatch):
    provider = ExpiredHistoryProvider()
    monkeypatch.setitem(app.extensions["mercury"], "mail_provider", lambda account: provider)
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        account.last_history_id = "12"
        db.session.commit()
        sync_account_history(account.id, account.connection_generation)
        db.session.refresh(account)
        recovery = db.session.scalar(
            select(ProcessingRun).where(ProcessingRun.kind == "checkpoint-recovery")
        )
        assert recovery is not None and recovery.status == "succeeded"
        assert recovery.requested_limit <= app.config["INDEX_MAX_THREADS"]
        assert account.last_history_id == provider.profile().history_id
        assert account.pending_sync is False


def test_admin_sees_operational_metrics_but_no_mailbox_content(app, client, connected):
    with app.app_context():
        user = db.session.scalar(select(User))
        result = app.test_cli_runner().invoke(args=["promote-admin", user.email])
        assert result.exit_code == 0, result.output
        subjects = db.session.scalars(select(EmailThread.subject)).all()
        summaries = db.session.scalars(select(ThreadAnalysis.summary)).all()
        senders = [thread.participants for thread in db.session.scalars(select(EmailThread)).all()]
    response = client.get("/admin/")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, private"
    html = response.get_data(as_text=True)
    assert "connected" in html.lower()
    for value in [*subjects, *summaries]:
        if value and len(value) > 6:
            assert value not in html
    for participants in senders:
        for participant in participants or []:
            for value in participant.values():
                if "@" in str(value):
                    assert str(value) not in html
    for secret_field in ("refresh_token", "access_token", "encrypted_token", "token_bundle"):
        assert secret_field not in html.lower()
