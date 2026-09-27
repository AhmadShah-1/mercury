"""Mercury's bucket meaning, split lineage, and live workspace updates in the interface."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from mercury.accounts.models import GmailAccount
from mercury.buckets.models import Bucket
from mercury.extensions import db
from mercury.inbox.models import EmailThread
from tests.bucket_vectors import make_bucket
from tests.conftest import csrf_token

HX = {"HX-Request": "true"}


def _renamed_split_bucket(app):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        parent = make_bucket(account, "Opportunities")
        child = make_bucket(
            account,
            "Recruiter Job Offers",
            ai_purpose="Offers and interview requests from recruiters.",
            split_from_id=parent.id,
        )
        child.name, child.user_confirmed = "Dream Jobs", True
        child.renamed_at = datetime.now(UTC) - timedelta(hours=1)
        db.session.commit()
        return parent.id, child.id


def test_bucket_shows_mercury_meaning_lineage_and_update_hint(app, client, connected):
    parent_id, child_id = _renamed_split_bucket(app)

    page = client.get(f"/app/buckets/{child_id}")

    assert page.status_code == 200
    body = page.data.decode()
    assert "Dream Jobs" in body
    assert 'title="Mercury: Recruiter Job Offers"' in body
    assert "Offers and interview requests from recruiters." in body
    assert "Meaning updated" in body
    assert f'href="/app/buckets/{parent_id}">Opportunities</a>' in body


def test_use_mercury_name_adopts_and_follows_it(app, client, connected):
    _, child_id = _renamed_split_bucket(app)
    token = csrf_token(client.get(f"/app/buckets/{child_id}/edit"))

    response = client.post(f"/app/buckets/{child_id}/follow-ai-name", data={"csrf_token": token})

    assert response.status_code == 302
    with app.app_context():
        bucket = db.session.get(Bucket, child_id)
        assert (bucket.name, bucket.user_confirmed) == ("Recruiter Job Offers", False)
    assert client.post(f"/app/buckets/{child_id}/follow-ai-name").status_code == 400


def test_workspace_polls_for_new_mail_and_reports_counts_only(app, client, connected):
    page = client.get("/app")
    assert b'hx-get="/app/updates?since=' in page.data
    since = int((datetime.now(UTC) - timedelta(minutes=5)).timestamp())

    quiet = client.get(f"/app/updates?since={since}", headers=HX)
    assert b"every 30s" in quiet.data and b"Your mailbox changed" not in quiet.data

    with app.app_context():
        thread = db.session.scalar(select(EmailThread).order_by(EmailThread.id))
        thread.latest_message_at = datetime.now(UTC)
        db.session.get(GmailAccount, thread.gmail_account_id).last_organized_at = datetime.now(UTC)
        db.session.commit()
        subject = thread.subject

    changed = client.get(f"/app/updates?since={since}", headers=HX)
    body = changed.data.decode()
    assert "1 new conversation and updated buckets" in body
    assert "every 30s" not in body
    assert subject not in body


def test_updates_poll_stops_for_signed_out_sessions(client):
    response = client.get("/app/updates?since=0", headers=HX)
    assert response.status_code == 286
    assert response.data == b""
