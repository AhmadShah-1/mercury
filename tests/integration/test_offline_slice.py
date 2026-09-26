from __future__ import annotations

from sqlalchemy import String, Text, cast, select

from mercury.accounts.models import GmailAccount
from mercury.extensions import db
from mercury.inbox.models import EmailThread, MessageReference, ProcessingRun, ThreadAnalysis
from mercury.integrations.fake_gmail import FIXTURE_THREADS
from tests.conftest import csrf_token


def test_complete_synthetic_workspace_flow(app, client, connected):
    workspace = client.get("/app")
    assert workspace.status_code == 200
    assert b"Revised launch forecast" in workspace.data
    assert b"Synthetic" in workspace.data
    assert workspace.headers["Cache-Control"] == "no-store, private"

    with app.app_context():
        thread = db.session.scalar(
            select(EmailThread).where(EmailThread.gmail_thread_id == "fixture-bank-html")
        )
        assert thread is not None
        thread_id = thread.id
        assert db.session.scalar(
            select(ThreadAnalysis).where(ThreadAnalysis.thread_id == thread.id)
        )

    reader = client.get(f"/app/threads/{thread_id}/body")
    assert reader.status_code == 200
    assert b"Statement ready" in reader.data
    assert b"tracker.invalid" not in reader.data
    assert b"PERSISTENCE_SENTINEL_BODY_ONLY" not in reader.data
    assert b"<script" not in reader.data


def test_index_persists_metadata_but_never_body_fixture_markers(app, connected):
    with app.app_context():
        assert db.session.scalar(select(GmailAccount)) is not None
        assert len(db.session.scalars(select(EmailThread)).all()) == len(FIXTURE_THREADS)
        expected_messages = sum(len(thread.messages) for thread in FIXTURE_THREADS)
        assert len(db.session.scalars(select(MessageReference)).all()) == expected_messages
        assert db.session.scalar(select(ProcessingRun)).status == "succeeded"

        for table in db.metadata.sorted_tables:
            for column in table.columns:
                if not isinstance(column.type, (String, Text)):
                    continue
                values = db.session.scalars(
                    select(cast(column, Text)).where(column.is_not(None))
                ).all()
                assert all("PERSISTENCE_SENTINEL_BODY_ONLY" not in value for value in values)


def test_all_mutations_keep_csrf_enabled(client, login):
    login()
    assert client.post("/auth/gmail/start", data={"accept_disclosure": "y"}).status_code == 400
    assert client.post("/auth/logout").status_code == 400
    assert client.post("/settings/delete", data={"confirmation": "DELETE"}).status_code == 400


def test_logout_with_csrf_clears_session(client, login):
    login()
    workspace = client.get("/app")
    token = csrf_token(workspace)
    response = client.post("/auth/logout", data={"csrf_token": token})
    assert response.status_code == 302
    assert client.get("/app").status_code == 302
