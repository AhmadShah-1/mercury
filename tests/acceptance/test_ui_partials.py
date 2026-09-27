"""UI partials, HTMX behavior, and safe reader error states.

HX-Request only selects a template; these tests confirm it never grants access, never bypasses
CSRF, and that provider failures render fixed, safe wording.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from mercury.buckets.models import Bucket, BucketAssignment
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ProcessingRun, ThreadAnalysis
from mercury.integrations.types import ProviderUnavailable, ReauthorizationRequired
from tests.conftest import csrf_token

HX = {"HX-Request": "true"}


def _connect_second_user(app, email="second@example.invalid"):
    """A genuinely separate user with its own synthetic mailbox (dev login is single-user)."""
    from mercury.accounts.models import User
    from mercury.accounts.service import connect_fake_mailbox
    from mercury.inbox.service import create_run, index_account

    with app.app_context():
        user = User(google_subject=f"subject-{email}", email=email, display_name="Second")
        db.session.add(user)
        db.session.commit()
        account = connect_fake_mailbox(user, ai_consent=False)
        index_account(account, create_run(user, account, kind="initial", limit=50), limit=50)
        user_id, generation = str(user.id), str(user.session_generation)
    other = app.test_client()
    with other.session_transaction() as session:
        session["_user_id"] = user_id
        session["_fresh"] = True
        session["session_generation"] = generation
    assert other.get("/app").status_code == 200
    return other


def _thread(app, gmail_thread_id="fixture-work-review", email="alex@example.invalid"):
    from mercury.accounts.models import User

    with app.app_context():
        user = db.session.scalar(select(User).where(User.email == email))
        return db.session.scalar(
            select(EmailThread).where(
                EmailThread.user_id == user.id, EmailThread.gmail_thread_id == gmail_thread_id
            )
        ).id


def test_reader_partial_is_selected_by_hx_request_but_still_owner_checked(app, client, connected):
    thread_id = _thread(app)
    full = client.get(f"/app/threads/{thread_id}")
    assert full.status_code == 200
    assert b"<!doctype html>" in full.data.lower()

    partial = client.get(f"/app/threads/{thread_id}", headers=HX)
    assert partial.status_code == 200
    assert b"<!doctype html>" not in partial.data.lower()
    assert b"Original subject" in partial.data
    assert b"AI summary" in partial.data
    assert b'rel="noopener noreferrer"' in partial.data
    assert f'id="thread-{thread_id}"'.encode() in partial.data
    assert b'hx-swap-oob="true"' in partial.data
    assert partial.headers["Cache-Control"] == "no-store, private"

    other = _connect_second_user(app)
    assert other.get(f"/app/threads/{thread_id}", headers=HX).status_code == 404
    assert other.get(f"/app/threads/{thread_id}/body", headers=HX).status_code == 404


def test_hx_request_does_not_authenticate(app, client, connected):
    thread_id = _thread(app)
    anonymous = app.test_client()
    response = anonymous.get(f"/app/threads/{thread_id}", headers=HX)
    assert response.status_code in {302, 401}
    assert b"Original subject" not in response.data


def test_opening_reader_marks_opened_in_mercury_without_touching_gmail_unread(
    app, client, connected
):
    thread_id = _thread(app)
    with app.app_context():
        before = db.session.get(EmailThread, thread_id)
        assert before.last_opened_at is None
        unread = before.gmail_unread
    workspace = client.get("/app")
    assert b"New in Mercury" in workspace.data
    assert b"Unread in Gmail" in workspace.data
    client.get(f"/app/threads/{thread_id}", headers=HX)
    with app.app_context():
        after = db.session.get(EmailThread, thread_id)
        assert after.last_opened_at is not None
        assert after.gmail_unread == unread


def test_htmx_mutations_still_require_csrf_and_return_partial_with_toast(app, client, connected):
    thread_id = _thread(app)
    rejected = client.post(
        f"/app/threads/{thread_id}/action", data={"status": "handled"}, headers=HX
    )
    assert rejected.status_code == 400

    reader = client.get(f"/app/threads/{thread_id}")
    token = csrf_token(reader)
    handled = client.post(
        f"/app/threads/{thread_id}/action",
        data={"status": "handled", "csrf_token": token},
        headers={**HX, "X-CSRFToken": token},
        follow_redirects=True,
    )
    assert handled.status_code == 200
    assert b"<!doctype html>" not in handled.data.lower()
    assert b"Marked handled in Mercury" in handled.data
    assert b'id="toast-stack" hx-swap-oob="beforeend"' in handled.data
    assert b"Reopen" in handled.data


def test_bulk_move_header_suppresses_per_thread_flash_only(app, client, connected):
    thread_id = _thread(app)
    with app.app_context():
        bucket_id = db.session.scalar(select(Bucket).where(Bucket.name == "Finance")).id
    token = csrf_token(client.get("/app"))
    moved = client.post(
        f"/app/threads/{thread_id}/move",
        data={"bucket_id": str(bucket_id), "csrf_token": token},
        headers={"X-CSRFToken": token, "X-Mercury-Bulk": "1"},
    )
    assert moved.status_code == 302
    with app.app_context():
        assignment = db.session.scalar(
            select(BucketAssignment).where(BucketAssignment.thread_id == thread_id)
        )
        assert assignment.bucket_id == bucket_id and assignment.locked_by_user
    assert b"Conversation moved" not in client.get("/app").data

    other = _connect_second_user(app)
    other_token = csrf_token(other.get("/app"))
    denied = other.post(
        f"/app/threads/{thread_id}/move",
        data={"bucket_id": str(bucket_id), "csrf_token": other_token},
        headers={"X-CSRFToken": other_token, "X-Mercury-Bulk": "1"},
    )
    assert denied.status_code in {400, 404}


def test_workspace_views_filter_owned_rows_and_escape_bucket_names(app, client, connected):
    page = client.get("/app/buckets/new")
    client.post(
        "/app/buckets/new",
        data={"name": "<b>Loud</b>", "purpose": "", "csrf_token": csrf_token(page)},
    )
    attention = client.get("/app?view=attention")
    assert attention.status_code == 200
    with app.app_context():
        open_subjects = {
            thread.subject
            for thread, analysis in db.session.execute(
                select(EmailThread, ThreadAnalysis).join(
                    ThreadAnalysis, ThreadAnalysis.thread_id == EmailThread.id
                )
            ).all()
            if analysis.action_required and analysis.action_status == "open"
        }
        closed_subjects = {
            thread.subject
            for thread in db.session.scalars(select(EmailThread))
            if thread.subject not in open_subjects
        }
    assert open_subjects
    for subject in open_subjects:
        assert subject.encode() in attention.data
    for subject in closed_subjects:
        assert f">{subject}</span>".encode() not in attention.data
    assert b"<b>Loud</b>" not in attention.data
    assert b"&lt;b&gt;Loud&lt;/b&gt;" in attention.data
    assert client.get("/app?view=unknown").status_code == 200

    unsorted = client.get("/app?view=unsorted")
    assert b"Unsorted" in unsorted.data


def test_progress_partial_polls_only_while_active_and_is_owner_checked(app, client, connected):
    with app.app_context():
        run = db.session.scalar(select(ProcessingRun))
        run_id = run.id
    done = client.get(f"/app/runs/{run_id}", headers=HX)
    assert done.status_code == 200
    assert b"<!doctype html>" not in done.data.lower()
    assert b"hx-trigger" not in done.data
    assert b"Your workspace is ready" in done.data

    with app.app_context():
        run = db.session.get(ProcessingRun, run_id)
        run.status, run.stage, run.found_count, run.completed_count = "running", "indexing", 9, 4
        db.session.commit()
    live = client.get(f"/app/runs/{run_id}", headers=HX)
    assert b'hx-trigger="every 2s"' in live.data
    assert b"Indexed 4 conversations" in live.data

    with app.app_context():
        run = db.session.get(ProcessingRun, run_id)
        run.stage, run.found_count, run.completed_count = "discovering_buckets", 9, 9
        db.session.commit()
    organizing = client.get(f"/app/runs/{run_id}", headers=HX)
    assert b'hx-trigger="every 2s"' in organizing.data
    assert b"Preparing summaries and category suggestions" in organizing.data

    with app.app_context():
        run = db.session.get(ProcessingRun, run_id)
        run.safe_error_code = "provider_rate_limited"
        db.session.commit()
    paused = client.get(f"/app/runs/{run_id}", headers=HX)
    assert b"hx-trigger" not in paused.data
    assert b"Processing paused" in paused.data

    other = _connect_second_user(app)
    assert other.get(f"/app/runs/{run_id}", headers=HX).status_code == 404


@pytest.mark.parametrize(
    ("error", "status", "expected"),
    [
        (LookupError("PROVIDER_SECRET_DETAIL"), 404, b"This message is no longer available"),
        (ReauthorizationRequired("PROVIDER_SECRET_DETAIL"), 409, b"Reconnect Gmail"),
        (
            ProviderUnavailable("provider_rate_limited", retry_after=30),
            503,
            b"Gmail is limiting requests right now; the summary above is still Mercury",
        ),
        (
            ProviderUnavailable("provider_timeout"),
            503,
            b"Gmail is temporarily unavailable; the summary above is still Mercury",
        ),
        (
            ProviderUnavailable("PROVIDER_SECRET_DETAIL"),
            503,
            b"Gmail is temporarily unavailable; the summary above is still Mercury",
        ),
    ],
)
def test_reader_body_provider_failures_render_safe_states(
    app, client, connected, monkeypatch, error, status, expected
):
    thread_id = _thread(app)
    provider = app.extensions["mercury"]["mail_provider"](None)

    def fail(_thread_id):
        raise error

    monkeypatch.setattr(provider, "get_thread", fail)
    response = client.get(f"/app/threads/{thread_id}/body", headers=HX)
    assert response.status_code == status
    assert expected in response.data
    assert b"PROVIDER_SECRET_DETAIL" not in response.data
    assert b"Traceback" not in response.data
    assert response.headers["Cache-Control"] == "no-store, private"
    if status == 503:
        assert b"Try again" in response.data
    if isinstance(error, ReauthorizationRequired):
        assert b"/auth/gmail/connect" in response.data
    if isinstance(error, ProviderUnavailable) and error.retry_after:
        assert response.headers["Retry-After"] == "30"


def test_action_without_analysis_uses_safe_error_page(app, client, connected):
    from sqlalchemy import delete, select

    from mercury.extensions import db
    from mercury.inbox.models import EmailThread, ThreadAnalysis

    with app.app_context():
        thread = db.session.scalar(select(EmailThread))
        db.session.execute(delete(ThreadAnalysis).where(ThreadAnalysis.thread_id == thread.id))
        db.session.commit()
        thread_id = thread.id
    page = client.get(f"/app/threads/{thread_id}")
    from tests.conftest import csrf_token

    response = client.post(
        f"/app/threads/{thread_id}/action",
        data={"status": "handled", "csrf_token": csrf_token(page)},
    )
    assert response.status_code == 409
    assert (
        b"That can&#39;t be done right now" in response.data
        or b"be done right now" in response.data
    )
    assert b"Werkzeug" not in response.data and b"Conflict" not in response.data
