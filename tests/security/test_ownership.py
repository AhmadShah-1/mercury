from __future__ import annotations

import uuid

from sqlalchemy import select

from mercury.accounts.models import User
from mercury.buckets.models import Bucket
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ProcessingRun


def _switch_login(client, user: User) -> None:
    with client.session_transaction() as session:
        session.clear()
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
        session["session_generation"] = str(user.session_generation)


def test_cross_user_thread_bucket_and_progress_ids_are_not_enumerable(app, client, connected):
    with app.app_context():
        owner_thread = db.session.scalar(select(EmailThread))
        owner_bucket = db.session.scalar(select(Bucket))
        owner_run = db.session.scalar(select(ProcessingRun))
        outsider = User(
            google_subject="outsider-subject",
            email="outsider@example.invalid",
            display_name="Outsider",
        )
        db.session.add(outsider)
        db.session.commit()
        db.session.refresh(outsider)
        ids = owner_thread.id, owner_bucket.id, owner_run.id
        outsider_id = outsider.id

    with app.app_context():
        outsider = db.session.get(User, outsider_id)
        _switch_login(client, outsider)

    thread_id, bucket_id, run_id = ids
    assert client.get(f"/app/threads/{thread_id}").status_code == 404
    assert client.get(f"/app/buckets/{bucket_id}").status_code == 404
    assert client.get(f"/app/runs/{run_id}").status_code == 404
    assert client.get("/admin/").status_code == 404


def test_session_generation_change_invalidates_existing_cookie(app, client, connected):
    with app.app_context():
        user = db.session.scalar(select(User))
        user.session_generation = uuid.uuid4()
        db.session.commit()
    assert client.get("/app").status_code == 401


def test_untrusted_host_is_rejected(client):
    response = client.get("/", headers={"Host": "attacker.invalid"})
    assert response.status_code == 400
