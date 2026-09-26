from __future__ import annotations

import uuid

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import select

from mercury.accounts.forms import EmptyForm
from mercury.buckets.forms import ActionForm, MoveThreadForm
from mercury.buckets.models import Bucket, BucketAssignment
from mercury.buckets.service import active_buckets, move_thread
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ThreadAnalysis
from mercury.inbox.reader import build_thread_view
from mercury.inbox.service import create_run, mail_provider_for, owned_run, owned_thread
from mercury.integrations.google.links import gmail_message_search_url, gmail_thread_url

bp = Blueprint("inbox", __name__)


def _workspace_query(bucket_id: uuid.UUID | None = None):
    query = (
        select(EmailThread, ThreadAnalysis, BucketAssignment, Bucket)
        .outerjoin(ThreadAnalysis, ThreadAnalysis.thread_id == EmailThread.id)
        .outerjoin(BucketAssignment, BucketAssignment.thread_id == EmailThread.id)
        .outerjoin(Bucket, Bucket.id == BucketAssignment.bucket_id)
        .where(EmailThread.user_id == current_user.id)
        .order_by(EmailThread.latest_message_at.desc(), EmailThread.id)
        .limit(100)
    )
    if bucket_id:
        query = query.where(Bucket.id == bucket_id, Bucket.user_id == current_user.id)
    return db.session.execute(query).all()


@bp.get("/app")
@login_required
def workspace():
    return render_template(
        "inbox/workspace.html",
        rows=_workspace_query(),
        buckets=active_buckets(current_user.id),
        selected_bucket=None,
        sync_form=EmptyForm(),
    )


@bp.get("/app/buckets/<uuid:bucket_id>")
@login_required
def bucket_workspace(bucket_id):
    bucket = db.session.scalar(
        select(Bucket).where(Bucket.id == bucket_id, Bucket.user_id == current_user.id)
    )
    if bucket is None:
        abort(404)
    return render_template(
        "inbox/workspace.html",
        rows=_workspace_query(bucket_id),
        buckets=active_buckets(current_user.id),
        selected_bucket=bucket,
        sync_form=EmptyForm(),
    )


@bp.get("/app/threads/<uuid:thread_id>")
@login_required
def thread_reader(thread_id):
    thread = owned_thread(current_user.id, thread_id)
    if thread is None:
        abort(404)
    analysis = db.session.scalar(
        select(ThreadAnalysis).where(ThreadAnalysis.thread_id == thread.id)
    )
    buckets = active_buckets(current_user.id)
    move_form = MoveThreadForm()
    move_form.bucket_id.choices = [(str(bucket.id), bucket.name) for bucket in buckets]
    reference = db.session.scalar(
        select(__import__("mercury.inbox.models", fromlist=["MessageReference"]).MessageReference)
        .where(
            __import__(
                "mercury.inbox.models", fromlist=["MessageReference"]
            ).MessageReference.thread_id
            == thread.id
        )
        .order_by(
            __import__(
                "mercury.inbox.models", fromlist=["MessageReference"]
            ).MessageReference.sent_at.desc()
        )
    )
    account = current_user.gmail_account
    return render_template(
        "inbox/reader.html",
        thread=thread,
        analysis=analysis,
        move_form=move_form,
        action_form=ActionForm(),
        open_url=gmail_thread_url(account.mailbox_address, thread.gmail_thread_id),
        search_url=(
            gmail_message_search_url(account.mailbox_address, reference.internet_message_id)
            if reference and reference.internet_message_id
            else None
        ),
    )


@bp.get("/app/threads/<uuid:thread_id>/body")
@login_required
def thread_body(thread_id):
    thread = owned_thread(current_user.id, thread_id)
    if thread is None:
        abort(404)
    account = current_user.gmail_account
    if account is None or account.connection_state != "connected":
        return render_template(
            "inbox/body_error.html", message="Reconnect Gmail to read this message."
        ), 409
    try:
        provider_thread = mail_provider_for(account).get_thread(thread.gmail_thread_id)
    except LookupError:
        return render_template(
            "inbox/body_error.html", message="This message is no longer available."
        ), 404
    view = build_thread_view(
        provider_thread,
        max_bytes=current_app.config["MAX_READER_BYTES"],
        max_messages=current_app.config["MAX_THREAD_MESSAGES"],
    )
    return render_template("inbox/body.html", view=view)


@bp.post("/app/threads/<uuid:thread_id>/move")
@login_required
def move(thread_id):
    form = MoveThreadForm()
    buckets = active_buckets(current_user.id)
    form.bucket_id.choices = [(str(bucket.id), bucket.name) for bucket in buckets]
    if not form.validate_on_submit():
        abort(400)
    move_thread(current_user.id, thread_id, uuid.UUID(form.bucket_id.data))
    return redirect(url_for("inbox.thread_reader", thread_id=thread_id))


@bp.post("/app/threads/<uuid:thread_id>/action")
@login_required
def action(thread_id):
    thread = owned_thread(current_user.id, thread_id)
    if thread is None:
        abort(404)
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    analysis = db.session.scalar(
        select(ThreadAnalysis).where(ThreadAnalysis.thread_id == thread.id)
    )
    if analysis is None:
        abort(409)
    analysis.action_status = form.status.data
    db.session.commit()
    return redirect(url_for("inbox.thread_reader", thread_id=thread_id))


@bp.post("/app/sync")
@login_required
def sync():
    form = EmptyForm()
    if not form.validate_on_submit():
        abort(400)
    account = current_user.gmail_account
    if account is None:
        return redirect(url_for("accounts.connect_page"))
    run = create_run(
        current_user, account, kind="manual", limit=current_app.config["INDEX_MAX_THREADS"]
    )
    if current_app.config["MAIL_MODE"] == "fake":
        from mercury.inbox.service import index_account
        from mercury.intelligence.service import analyze_pending

        index_account(account, run, limit=run.requested_limit)
        if account.ai_consent:
            analyze_pending(current_user.id)
    else:
        from mercury.jobs.tasks import enqueue_discovery

        enqueue_discovery(current_app.extensions["mercury"]["queue"], account, run)
    return redirect(url_for("inbox.run_status", run_id=run.id))


@bp.get("/app/runs/<uuid:run_id>")
@login_required
def run_status(run_id):
    run = owned_run(current_user.id, run_id)
    if run is None:
        abort(404)
    if request.accept_mimetypes.best == "application/json":
        return jsonify(
            id=str(run.id),
            stage=run.stage,
            status=run.status,
            found=run.found_count,
            completed=run.completed_count,
            error=run.safe_error_code,
        )
    return render_template("inbox/progress.html", run=run)
