from __future__ import annotations

import uuid
from datetime import UTC, datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import and_, func, or_, select

from mercury.accounts.forms import EmptyForm
from mercury.buckets.forms import ActionForm, MoveThreadForm
from mercury.buckets.models import Bucket, BucketAssignment
from mercury.buckets.service import active_buckets, move_thread
from mercury.extensions import db
from mercury.inbox.models import EmailThread, MessageReference, ProcessingRun, ThreadAnalysis
from mercury.inbox.reader import build_thread_view
from mercury.inbox.service import create_run, mail_provider_for, owned_run, owned_thread
from mercury.integrations.google.links import gmail_message_search_url, gmail_thread_url
from mercury.integrations.types import ProviderUnavailable, ReauthorizationRequired

bp = Blueprint("inbox", __name__)

# Display-only list filters. Every one is applied on top of the owner-filtered query.
WORKSPACE_VIEWS = {
    "overview": "Overview",
    "attention": "Needs attention",
    "all": "All indexed threads",
    "unsorted": "Unsorted",
}
SAFE_PROVIDER_CODES = {"provider_unavailable", "provider_rate_limited", "provider_timeout"}
# A run that has not finished after this long stops live polling and asks for a manual refresh.
PROGRESS_POLL_WINDOW_SECONDS = 30 * 60


def _is_htmx() -> bool:
    """HX-Request only selects a partial template; it never changes authorization."""
    return request.headers.get("HX-Request") == "true"


@bp.app_template_filter("shortdate")
def shortdate(value: datetime | None) -> str:
    if value is None:
        return ""
    moment = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if moment.date() == now.date():
        return moment.strftime("%H:%M")
    if moment.year == now.year:
        return f"{moment:%b} {moment.day}"
    return f"{moment:%b} {moment.day}, {moment.year}"


@bp.app_template_filter("longdate")
def longdate(value: datetime | None) -> str:
    if value is None:
        return ""
    moment = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    return f"{moment:%a} {moment:%b} {moment.day}, {moment.year} · {moment:%H:%M} UTC"


def _workspace_query(bucket_id: uuid.UUID | None = None, view: str = "overview"):
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
    elif view == "attention":
        query = query.where(
            ThreadAnalysis.action_required.is_(True), ThreadAnalysis.action_status == "open"
        )
    elif view == "unsorted":
        query = query.where(or_(Bucket.id.is_(None), Bucket.archived.is_(True)))
    return db.session.execute(query).all()


def _workspace_counts(user_id: uuid.UUID) -> dict:
    """Aggregate counts for navigation badges; scoped to one owner and returns no content."""
    open_action = and_(
        ThreadAnalysis.action_required.is_(True), ThreadAnalysis.action_status == "open"
    )
    total, unread, unopened, attention, unsorted = db.session.execute(
        select(
            func.count(EmailThread.id),
            func.count(EmailThread.id).filter(EmailThread.gmail_unread.is_(True)),
            func.count(EmailThread.id).filter(EmailThread.last_opened_at.is_(None)),
            func.count(EmailThread.id).filter(open_action),
            func.count(EmailThread.id).filter(or_(Bucket.id.is_(None), Bucket.archived.is_(True))),
        )
        .select_from(EmailThread)
        .outerjoin(ThreadAnalysis, ThreadAnalysis.thread_id == EmailThread.id)
        .outerjoin(BucketAssignment, BucketAssignment.thread_id == EmailThread.id)
        .outerjoin(Bucket, Bucket.id == BucketAssignment.bucket_id)
        .where(EmailThread.user_id == user_id)
    ).one()
    per_bucket = dict(
        db.session.execute(
            select(BucketAssignment.bucket_id, func.count())
            .where(BucketAssignment.user_id == user_id, BucketAssignment.bucket_id.is_not(None))
            .group_by(BucketAssignment.bucket_id)
        ).all()
    )
    return {
        "total": total,
        "unread": unread,
        "unopened": unopened,
        "attention": attention,
        "unsorted": unsorted,
        "per_bucket": per_bucket,
    }


def _latest_run(user_id: uuid.UUID) -> ProcessingRun | None:
    return db.session.scalar(
        select(ProcessingRun)
        .where(ProcessingRun.user_id == user_id)
        .order_by(ProcessingRun.created_at.desc())
        .limit(1)
    )


def _render_workspace(*, rows, selected_bucket=None, view: str = "overview"):
    buckets = active_buckets(current_user.id)
    return render_template(
        "inbox/workspace.html",
        rows=rows,
        buckets=buckets,
        selected_bucket=selected_bucket,
        view=view,
        view_label=selected_bucket.name if selected_bucket else WORKSPACE_VIEWS[view],
        views=WORKSPACE_VIEWS,
        counts=_workspace_counts(current_user.id) if current_user.gmail_account else None,
        latest_run=_latest_run(current_user.id) if current_user.gmail_account else None,
        sync_form=EmptyForm(),
        move_form=EmptyForm(),
    )


@bp.get("/app")
@login_required
def workspace():
    view = request.args.get("view", "overview")
    if view not in WORKSPACE_VIEWS:
        view = "overview"
    return _render_workspace(rows=_workspace_query(view=view), view=view)


@bp.get("/app/buckets/<uuid:bucket_id>")
@login_required
def bucket_workspace(bucket_id):
    bucket = db.session.scalar(
        select(Bucket).where(Bucket.id == bucket_id, Bucket.user_id == current_user.id)
    )
    if bucket is None:
        abort(404)
    return _render_workspace(rows=_workspace_query(bucket_id), selected_bucket=bucket)


@bp.get("/app/threads/<uuid:thread_id>")
@login_required
def thread_reader(thread_id):
    thread = owned_thread(current_user.id, thread_id)
    if thread is None:
        abort(404)
    analysis = db.session.scalar(
        select(ThreadAnalysis).where(
            ThreadAnalysis.thread_id == thread.id, ThreadAnalysis.user_id == current_user.id
        )
    )
    placement = db.session.execute(
        select(BucketAssignment, Bucket)
        .outerjoin(
            Bucket,
            and_(Bucket.id == BucketAssignment.bucket_id, Bucket.user_id == current_user.id),
        )
        .where(
            BucketAssignment.thread_id == thread.id,
            BucketAssignment.user_id == current_user.id,
        )
    ).first()
    assignment, bucket = placement if placement else (None, None)
    buckets = active_buckets(current_user.id)
    move_form = MoveThreadForm()
    move_form.bucket_id.choices = [(str(item.id), item.name) for item in buckets]
    if bucket is not None and not bucket.archived:
        move_form.bucket_id.data = str(bucket.id)
    reference = db.session.scalar(
        select(MessageReference)
        .where(
            MessageReference.thread_id == thread.id,
            MessageReference.user_id == current_user.id,
        )
        .order_by(MessageReference.sent_at.desc())
        .limit(1)
    )
    first_open = thread.last_opened_at is None
    if first_open:
        # Mercury-local "opened" marker only; Gmail's unread state is never modified.
        thread.last_opened_at = datetime.now(UTC)
        db.session.commit()
    account = current_user.gmail_account
    return render_template(
        "inbox/_reader_panel.html" if _is_htmx() else "inbox/reader.html",
        thread=thread,
        analysis=analysis,
        assignment=assignment,
        bucket=bucket,
        buckets=buckets,
        account=account,
        latest_reference=reference,
        move_form=move_form,
        action_form=ActionForm(),
        open_url=gmail_thread_url(account.mailbox_address, thread.gmail_thread_id),
        search_url=(
            gmail_message_search_url(account.mailbox_address, reference.internet_message_id)
            if reference and reference.internet_message_id
            else None
        ),
    )


def _body_error(thread, kind: str, status: int, **extra):
    return render_template("inbox/body_error.html", thread=thread, kind=kind, **extra), status


@bp.get("/app/threads/<uuid:thread_id>/body")
@login_required
def thread_body(thread_id):
    thread = owned_thread(current_user.id, thread_id)
    if thread is None:
        abort(404)
    account = current_user.gmail_account
    if account is None or account.connection_state != "connected":
        state = account.connection_state if account else "disconnected"
        kind = "disconnected" if state in {"deleting", "disconnected"} else "reauth"
        return _body_error(thread, kind, 409)
    try:
        provider_thread = mail_provider_for(account).get_thread(thread.gmail_thread_id)
    except LookupError:
        return _body_error(thread, "deleted", 404)
    except ReauthorizationRequired:
        return _body_error(thread, "reauth", 409)
    except ProviderUnavailable as exc:
        code = str(exc) if str(exc) in SAFE_PROVIDER_CODES else "provider_unavailable"
        response, status = _body_error(thread, code, 503)
        headers = {}
        if isinstance(exc.retry_after, int) and 0 < exc.retry_after <= 3600:
            headers["Retry-After"] = str(exc.retry_after)
        return response, status, headers
    view = build_thread_view(
        provider_thread,
        max_bytes=current_app.config["MAX_READER_BYTES"],
        max_messages=current_app.config["MAX_THREAD_MESSAGES"],
    )
    return render_template("inbox/body.html", view=view, thread=thread)


@bp.post("/app/threads/<uuid:thread_id>/move")
@login_required
def move(thread_id):
    form = MoveThreadForm()
    buckets = active_buckets(current_user.id)
    form.bucket_id.choices = [(str(bucket.id), bucket.name) for bucket in buckets]
    if not form.validate_on_submit():
        abort(400)
    bucket_id = uuid.UUID(form.bucket_id.data)
    try:
        move_thread(current_user.id, thread_id, bucket_id)
    except LookupError:
        abort(404)
    account = current_user.gmail_account
    if account and current_app.config["GMAIL_LABEL_WRITES_ENABLED"] and account.label_write_consent:
        from mercury.jobs.tasks import enqueue_label

        enqueue_label(
            current_app.extensions["mercury"]["queue"],
            account,
            thread_id=thread_id,
            bucket_id=bucket_id,
        )
    flash("Conversation moved. Mercury will keep it there.", "success")
    return redirect(url_for("inbox.thread_reader", thread_id=thread_id))


ACTION_MESSAGES = {
    "handled": "Marked handled in Mercury. Nothing was changed in Gmail.",
    "dismissed": "Marked as not an action.",
    "open": "Possible action reopened.",
}


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
    flash(ACTION_MESSAGES[form.status.data], "success")
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
    created = run.created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - created).total_seconds() if created else 0
    active = run.status in {"pending", "running"} and not run.safe_error_code
    return render_template(
        "inbox/_progress.html" if _is_htmx() else "inbox/progress.html",
        run=run,
        polling=active and age < PROGRESS_POLL_WINDOW_SECONDS,
        overdue=active and age >= PROGRESS_POLL_WINDOW_SECONDS,
        slow=active and age >= 5 * 60,
        checked_at=datetime.now(UTC),
        sync_form=EmptyForm(),
    )
