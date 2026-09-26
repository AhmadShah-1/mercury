from sqlalchemy import func, select

from mercury.accounts.models import GmailAccount, SecurityAuditEvent, User
from mercury.extensions import db
from mercury.inbox.models import EmailThread
from tests.conftest import csrf_token


def test_disconnect_removes_tokens_and_all_mailbox_derived_records(app, client, connected):
    settings = client.get("/settings")
    response = client.post(
        "/settings/disconnect",
        data={"csrf_token": csrf_token(settings)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(select(User)) is not None
        assert db.session.scalar(select(GmailAccount)) is None
        assert db.session.scalar(select(func.count()).select_from(EmailThread)) == 0
        event = db.session.scalar(
            select(SecurityAuditEvent).where(SecurityAuditEvent.event_type == "gmail_disconnected")
        )
        assert event is not None
    assert client.get("/app").status_code == 302


def test_account_deletion_and_replay_are_idempotent(app, client, connected, tmp_path):
    settings = client.get("/settings")
    response = client.post(
        "/settings/delete",
        data={"confirmation": "DELETE", "csrf_token": csrf_token(settings)},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(select(User)) is None
        event = db.session.scalar(
            select(SecurityAuditEvent).where(SecurityAuditEvent.event_type == "account_deleted")
        )
        user_id = event.resource_id

    runner = app.test_cli_runner()
    exported = runner.invoke(args=["export-deletions", "--since", "2000-01-01T00:00:00Z"])
    assert exported.exit_code == 0
    assert str(user_id) in exported.output
    event_file = tmp_path / "deletions.jsonl"
    event_file.write_text(exported.output)
    first = runner.invoke(args=["replay-deletions", str(event_file)])
    second = runner.invoke(args=["replay-deletions", str(event_file)])
    assert first.exit_code == second.exit_code == 0
    assert "Replayed 1 deletion events" in second.output
