from __future__ import annotations

import uuid

from sqlalchemy import select

from mercury.accounts.models import GmailAccount, User
from mercury.buckets.crates import create_crate
from mercury.buckets.models import Bucket, Crate
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ProcessingRun
from tests.conftest import csrf_token


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


def test_cross_user_crates_and_bucket_placements_are_unreachable(app, client, connected):
    with app.app_context():
        owner_bucket = db.session.scalar(select(Bucket).where(Bucket.name == "Work"))
        misc = db.session.scalar(select(Crate).where(Crate.kind == "misc"))
        owner_crate = create_crate(owner_bucket.user_id, [owner_bucket.id], "Private")
        ids = owner_bucket.id, owner_crate.id, misc.id
    bucket_id, crate_id, misc_id = ids

    # A second, fully connected user with their own mailbox and bucket.
    with app.app_context():
        outsider = User(
            google_subject="outsider-subject",
            email="outsider@example.invalid",
            display_name="Outsider",
        )
        db.session.add(outsider)
        db.session.flush()
        account = GmailAccount(
            user_id=outsider.id,
            provider_subject="outsider-mailbox",
            mailbox_address="outsider@example.invalid",
            granted_scopes=["fixture:gmail.readonly"],
            disclosure_version="2026-09-v1",
        )
        db.session.add(account)
        db.session.flush()
        own_bucket = Bucket(user_id=outsider.id, gmail_account_id=account.id, name="Mine")
        db.session.add(own_bucket)
        db.session.commit()
        own_bucket_id, outsider_id = own_bucket.id, outsider.id
        _switch_login(client, outsider)

    token = csrf_token(client.get("/app/buckets/new"))
    assert client.get(f"/app/crates/{crate_id}").status_code == 404
    assert client.get(f"/app/crates/{misc_id}").status_code == 404
    for url, data in [
        (f"/app/buckets/{bucket_id}/crate", {"crate_id": ""}),
        (f"/app/buckets/{bucket_id}/favorite", {"favorite": "1"}),
        (f"/app/crates/{crate_id}/rename", {"name": "Stolen"}),
        (f"/app/crates/{crate_id}/favorite", {"favorite": "1"}),
        (f"/app/crates/{crate_id}/dissolve", {}),
        (f"/app/crates/{crate_id}/combine", {"target_id": str(misc_id)}),
    ]:
        assert client.post(url, data={**data, "csrf_token": token}).status_code == 404, url
    # Their own bucket cannot be placed into, or crated with, someone else's records.
    for data in (
        {"crate_id": str(crate_id)},
        {"crate_id": "new", "with_bucket_id": str(bucket_id)},
    ):
        response = client.post(
            f"/app/buckets/{own_bucket_id}/crate", data={**data, "csrf_token": token}
        )
        assert response.status_code in {400, 404}
    stolen = client.post("/app/crates", data={"bucket_ids": [str(bucket_id)], "csrf_token": token})
    assert stolen.status_code in {400, 404}

    with app.app_context():
        owner_crate = db.session.get(Crate, crate_id)
        assert owner_crate.name == "Private" and owner_crate.favorite is False
        assert db.session.get(Bucket, bucket_id).crate_id == crate_id
        assert db.session.get(Bucket, bucket_id).favorite is False
        assert db.session.get(Bucket, own_bucket_id).crate_id is None
        assert db.session.scalar(select(Crate).where(Crate.user_id == outsider_id)) is None


def test_session_generation_change_invalidates_existing_cookie(app, client, connected):
    with app.app_context():
        user = db.session.scalar(select(User))
        user.session_generation = uuid.uuid4()
        db.session.commit()
    assert client.get("/app").status_code == 401


def test_untrusted_host_is_rejected(client):
    response = client.get("/", headers={"Host": "attacker.invalid"})
    assert response.status_code == 400
