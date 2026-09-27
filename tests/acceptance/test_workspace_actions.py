from __future__ import annotations

from sqlalchemy import select

from mercury.buckets.models import Bucket, BucketAssignment, Crate
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ThreadAnalysis
from tests.conftest import csrf_token


def test_workspace_bucket_move_action_and_reversible_crate(app, client, connected):
    create_page = client.get("/app/buckets/new")
    created = client.post(
        "/app/buckets/new",
        data={
            "name": 'Follow up <img src="https://attacker.invalid">',
            "purpose": "User-created destination",
            "csrf_token": csrf_token(create_page),
        },
        follow_redirects=False,
    )
    assert created.status_code == 302

    with app.app_context():
        bucket = db.session.scalar(select(Bucket).where(Bucket.name.like("Follow up%")))
        work = db.session.scalar(
            select(EmailThread).where(EmailThread.gmail_thread_id == "fixture-work-review")
        )
        bucket_id, thread_id = bucket.id, work.id

    bucket_page = client.get(f"/app/buckets/{bucket_id}")
    assert b'<img src="https://attacker.invalid">' not in bucket_page.data
    assert b"&lt;img" in bucket_page.data

    reader = client.get(f"/app/threads/{thread_id}")
    assert b"Original subject" in reader.data
    assert b"AI summary" in reader.data
    assert b"Open in Gmail" in reader.data
    token = csrf_token(reader)
    moved = client.post(
        f"/app/threads/{thread_id}/move",
        data={"bucket_id": str(bucket_id), "csrf_token": token},
        follow_redirects=False,
    )
    assert moved.status_code == 302
    handled = client.post(
        f"/app/threads/{thread_id}/action",
        data={"status": "handled", "csrf_token": token},
        follow_redirects=False,
    )
    assert handled.status_code == 302
    with app.app_context():
        assignment = db.session.scalar(
            select(BucketAssignment).where(BucketAssignment.thread_id == thread_id)
        )
        analysis = db.session.scalar(
            select(ThreadAnalysis).where(ThreadAnalysis.thread_id == thread_id)
        )
        assert assignment.bucket_id == bucket_id
        assert assignment.locked_by_user is True
        assert analysis.action_status == "handled"

        source = db.session.scalar(select(Bucket).where(Bucket.name == "Finance"))
        destination = db.session.scalar(select(Bucket).where(Bucket.name == "Purchases"))
        source_id, destination_id = source.id, destination.id

    # Combining buckets now makes a crate: nothing is archived or reassigned, and it undoes.
    token = csrf_token(client.get(f"/app/buckets/{source_id}"))
    crated = client.post(
        f"/app/buckets/{source_id}/crate",
        data={"crate_id": "new", "with_bucket_id": str(destination_id), "csrf_token": token},
        follow_redirects=False,
    )
    assert crated.status_code == 303
    with app.app_context():
        source = db.session.get(Bucket, source_id)
        crate_id = source.crate_id
        assert source.archived is False
        assert db.session.get(Bucket, destination_id).crate_id == crate_id
    crate_page = client.get(f"/app/crates/{crate_id}")
    assert crate_page.status_code == 200
    assert b"Monthly statement notice" in crate_page.data
    assert b"Your order has shipped" in crate_page.data

    dissolved = client.post(
        f"/app/crates/{crate_id}/dissolve", data={"csrf_token": token}, follow_redirects=False
    )
    assert dissolved.status_code == 303
    with app.app_context():
        assert db.session.get(Bucket, source_id).crate_id is None
        assert db.session.get(Bucket, destination_id).crate_id is None


def test_unsorted_is_a_fixed_misc_bucket_and_manual_destination(app, client, connected):
    with app.app_context():
        assignment = db.session.scalar(
            select(BucketAssignment).where(BucketAssignment.bucket_id.is_not(None))
        )
        thread = db.session.get(EmailThread, assignment.thread_id)
        thread_id, subject = thread.id, thread.subject
        bucket_count = len(db.session.scalars(select(Bucket)).all())
        misc_id = db.session.scalar(select(Crate).where(Crate.kind == "misc")).id

    reader = client.get(f"/app/threads/{thread_id}")
    moved = client.post(
        f"/app/threads/{thread_id}/move",
        data={"bucket_id": "unsorted", "csrf_token": csrf_token(reader)},
        follow_redirects=False,
    )
    assert moved.status_code == 302

    with app.app_context():
        assignment = db.session.scalar(
            select(BucketAssignment).where(BucketAssignment.thread_id == thread_id)
        )
        assert assignment.bucket_id is None and assignment.locked_by_user
        assert len(db.session.scalars(select(Bucket)).all()) == bucket_count

    assert subject.encode() in client.get("/app?view=unsorted").data
    assert subject.encode() in client.get(f"/app/crates/{misc_id}").data


def test_sender_rules_are_managed_in_settings(app, client, connected):
    from mercury.buckets.models import SenderRule

    workspace = client.get("/app")
    assert b"Sender rules" not in workspace.data
    old = client.get("/app/rules", follow_redirects=False)
    assert old.status_code == 302
    assert old.headers["Location"].endswith("/settings#sender-rules")

    settings = client.get("/settings")
    assert b'id="sender-rules"' in settings.data
    with app.app_context():
        bucket = db.session.scalar(select(Bucket).where(Bucket.archived.is_(False)))
        bucket_id, bucket_name = bucket.id, bucket.name

    token = csrf_token(settings)
    missing_csrf = client.post(
        "/settings/rules", data={"sender_address": "a@example.invalid", "bucket_id": bucket_id}
    )
    assert missing_csrf.status_code == 400
    invalid = client.post(
        "/settings/rules",
        data={"sender_address": "", "bucket_id": str(bucket_id), "csrf_token": token},
    )
    assert invalid.status_code == 400
    assert b'id="sender-rules"' in invalid.data

    saved = client.post(
        "/settings/rules",
        data={
            "sender_address": "Billing@Example.invalid",
            "bucket_id": str(bucket_id),
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert saved.status_code == 302
    assert saved.headers["Location"].endswith("/settings#sender-rules")
    with app.app_context():
        rule = db.session.scalar(select(SenderRule))
        assert rule.bucket_id == bucket_id
        address = rule.sender_address
    listed = client.get("/settings")
    assert address.encode() in listed.data
    assert bucket_name.encode() in listed.data


def test_reader_actions_rail_and_collapsed_original_text(app, client, connected):
    with app.app_context():
        thread_id = db.session.scalar(
            select(EmailThread.id).where(EmailThread.gmail_thread_id == "fixture-work-review")
        )
    reader = client.get(f"/app/threads/{thread_id}", headers={"HX-Request": "true"})
    assert b'class="reader-rail"' in reader.data
    assert b"Move to bucket" in reader.data
    assert b"Summaries can be incomplete or wrong" not in reader.data
    # Original text stays collapsed, and is fetched from Gmail only when first opened.
    assert b'<details class="messages" data-messages>' in reader.data
    assert b'hx-trigger="toggle once from:closest details"' in reader.data
    assert b'hx-trigger="load"' not in reader.data
