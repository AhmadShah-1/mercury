from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

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
from mercury.buckets.crates import build_library, owned_crate
from mercury.buckets.forms import ActionForm, MoveThreadForm
from mercury.buckets.models import Bucket, BucketAssignment, Crate
from mercury.buckets.service import UNSORTED_VALUE, active_buckets, move_thread
from mercury.extensions import db
from mercury.inbox.models import EmailThread, MessageReference, ProcessingRun, ThreadAnalysis
from mercury.inbox.reader import build_thread_view
from mercury.inbox.service import (
    active_run,
    create_run,
    mail_provider_for,
    owned_run,
    owned_thread,
)
from mercury.integrations.google.links import gmail_message_search_url, gmail_thread_url
from mercury.integrations.types import ProviderUnavailable, ReauthorizationRequired

bp = Blueprint("inbox", __name__)

# Display-only list filters. Every one is applied on top of the owner-filtered query.
WORKSPACE_VIEWS = {
    "overview": "Overview",
    "attention": "Needs attention",
    "unsorted": "Unsorted",
}
WORKSPACE_NAV_VIEWS = {
    "overview": "Overview",
    "attention": "Needs attention",
}
SAFE_PROVIDER_CODES = {"provider_unavailable", "provider_rate_limited", "provider_timeout"}
# A run that has not finished after this long stops live polling and asks for a manual refresh.
# Matches the worker's abandoned-run bound, since a full 2,000-thread import can take an hour.
PROGRESS_POLL_WINDOW_SECONDS = 2 * 60 * 60


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


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _cursor_for(thread: EmailThread) -> str:
    moment = thread.latest_message_at
    moment = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    # Integer microseconds round-trip exactly, which the keyset equality comparison needs.
    return f"{(moment - _EPOCH) // timedelta(microseconds=1)}_{thread.id}"


def _parse_cursor(value: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not value:
        return None
    try:
        micros, thread_id = value.split("_", 1)
        return _EPOCH + timedelta(microseconds=int(micros)), uuid.UUID(thread_id)
    except (OverflowError, ValueError):
        return None


def _workspace_query(
    bucket_id: uuid.UUID | None = None,
    view: str = "overview",
    cursor: tuple[datetime, uuid.UUID] | None = None,
    crate_id: uuid.UUID | None = None,
    include_unsorted: bool = False,
):
    """One page (plus one row to detect more) in newest-first keyset order.

    Pages are ``INBOX_PAGE_SIZE`` long; older ones load by cursor, never as one mailbox list.
    """
    query = (
        select(EmailThread, ThreadAnalysis, BucketAssignment, Bucket)
        # Every joined row is owner-filtered too, in addition to the composite tenant FKs.
        .outerjoin(
            ThreadAnalysis,
            and_(
                ThreadAnalysis.thread_id == EmailThread.id,
                ThreadAnalysis.user_id == current_user.id,
            ),
        )
        .outerjoin(
            BucketAssignment,
            and_(
                BucketAssignment.thread_id == EmailThread.id,
                BucketAssignment.user_id == current_user.id,
            ),
        )
        .outerjoin(
            Bucket,
            and_(Bucket.id == BucketAssignment.bucket_id, Bucket.user_id == current_user.id),
        )
        .where(EmailThread.user_id == current_user.id)
        .order_by(EmailThread.latest_message_at.desc(), EmailThread.id)
        .limit(current_app.config["INBOX_PAGE_SIZE"] + 1)
    )
    if cursor is not None:
        latest, thread_id = cursor
        query = query.where(
            or_(
                EmailThread.latest_message_at < latest,
                and_(EmailThread.latest_message_at == latest, EmailThread.id > thread_id),
            )
        )
    if crate_id:
        # A crate lists its active buckets' conversations together, as one list.
        in_crate = and_(Bucket.crate_id == crate_id, Bucket.archived.is_(False))
        query = query.where(
            or_(in_crate, Bucket.id.is_(None), Bucket.archived.is_(True))
            if include_unsorted
            else in_crate
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


def _split_parent(bucket: Bucket | None) -> Bucket | None:
    if bucket is None or bucket.split_from_id is None:
        return None
    return db.session.scalar(
        select(Bucket).where(Bucket.id == bucket.split_from_id, Bucket.user_id == current_user.id)
    )


def _render_workspace(
    *,
    rows,
    selected_bucket=None,
    selected_crate: Crate | None = None,
    crate_filter: Bucket | None = None,
    view: str = "overview",
    paged=False,
):
    page_size = current_app.config["INBOX_PAGE_SIZE"]
    rows, more = rows[:page_size], len(rows) > page_size
    more_url = None
    if more:
        args = dict(request.view_args or {})
        if crate_filter is not None:
            args["bucket"] = crate_filter.id
        elif selected_bucket is None and selected_crate is None and view != "overview":
            args["view"] = view
        more_url = url_for(request.endpoint, before=_cursor_for(rows[-1][0]), **args)
    if paged and _is_htmx():
        # "Show older" appends the next page in place of its own list item.
        return render_template(
            "inbox/_thread_page.html",
            rows=rows,
            more_url=more_url,
            account=current_user.gmail_account,
        )
    buckets = active_buckets(current_user.id)
    connected = current_user.gmail_account is not None
    counts = _workspace_counts(current_user.id) if connected else None
    if selected_crate is not None:
        view_label = selected_crate.name
    else:
        view_label = selected_bucket.name if selected_bucket else WORKSPACE_VIEWS[view]
    return render_template(
        "inbox/workspace.html",
        rows=rows,
        more_url=more_url,
        paged=paged,
        buckets=buckets,
        library=(
            build_library(
                current_user.id,
                buckets=buckets,
                sizes=counts["per_bucket"],
                selected_bucket=selected_bucket,
                selected_crate=selected_crate,
                selected_unsorted=(
                    view == "unsorted" and selected_bucket is None and selected_crate is None
                ),
                unsorted_count=counts["unsorted"],
            )
            if connected
            else None
        ),
        selected_bucket=selected_bucket,
        selected_crate=selected_crate,
        crate_filter=crate_filter,
        next_path=request.full_path.rstrip("?"),
        view=view,
        view_label=view_label,
        split_from=_split_parent(selected_bucket),
        updates_since=int(datetime.now(UTC).timestamp()),
        views=WORKSPACE_NAV_VIEWS,
        counts=counts,
        latest_run=_latest_run(current_user.id) if connected else None,
        move_form=EmptyForm(),
        unsorted_value=UNSORTED_VALUE,
    )


@bp.get("/app")
@login_required
def workspace():
    view = request.args.get("view", "overview")
    if view == "all":
        view = "overview"
    if view not in WORKSPACE_VIEWS:
        view = "overview"
    cursor = _parse_cursor(request.args.get("before"))
    return _render_workspace(
        rows=_workspace_query(view=view, cursor=cursor), view=view, paged=cursor is not None
    )


@bp.get("/app/buckets/<uuid:bucket_id>")
@login_required
def bucket_workspace(bucket_id):
    bucket = db.session.scalar(
        select(Bucket).where(Bucket.id == bucket_id, Bucket.user_id == current_user.id)
    )
    if bucket is None:
        abort(404)
    cursor = _parse_cursor(request.args.get("before"))
    return _render_workspace(
        rows=_workspace_query(bucket_id, cursor=cursor),
        selected_bucket=bucket,
        paged=cursor is not None,
    )


@bp.get("/app/crates/<uuid:crate_id>")
@login_required
def crate_workspace(crate_id):
    """Every conversation in a crate's buckets as one list, optionally narrowed to one bucket."""
    crate = owned_crate(current_user.id, crate_id)
    if crate is None:
        abort(404)
    crate_filter = None
    try:
        member_id = uuid.UUID(request.args.get("bucket", ""))
    except ValueError:
        member_id = None
    if member_id is not None:
        # Only a member of this same crate narrows the list; any other ID shows the whole crate.
        crate_filter = db.session.scalar(
            select(Bucket).where(
                Bucket.id == member_id,
                Bucket.user_id == current_user.id,
                Bucket.crate_id == crate.id,
                Bucket.archived.is_(False),
            )
        )
    cursor = _parse_cursor(request.args.get("before"))
    return _render_workspace(
        rows=_workspace_query(
            crate_filter.id if crate_filter else None,
            cursor=cursor,
            crate_id=crate.id,
            include_unsorted=crate.is_misc and crate_filter is None,
        ),
        selected_crate=crate,
        crate_filter=crate_filter,
        paged=cursor is not None,
    )


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
    move_form.bucket_id.choices = [(UNSORTED_VALUE, "Unsorted")] + [
        (str(item.id), item.name) for item in buckets
    ]
    if bucket is not None and not bucket.archived:
        move_form.bucket_id.data = str(bucket.id)
    else:
        move_form.bucket_id.data = UNSORTED_VALUE
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
    form.bucket_id.choices = [(UNSORTED_VALUE, "Unsorted")] + [
        (str(bucket.id), bucket.name) for bucket in buckets
    ]
    if not form.validate_on_submit():
        abort(400)
    bucket_id = None if form.bucket_id.data == UNSORTED_VALUE else uuid.UUID(form.bucket_id.data)
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
    if request.headers.get("X-Mercury-Bulk") == "1":
        # Bulk and drag moves show one summary toast client-side instead of one flash per
        # thread; 204 (never a redirect) lets the script tell success from a sign-in redirect.
        return "", 204
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
        select(ThreadAnalysis).where(
            ThreadAnalysis.thread_id == thread.id, ThreadAnalysis.user_id == current_user.id
        )
    )
    if analysis is None:
        abort(409)
    analysis.action_status = form.status.data
    db.session.commit()
    flash(ACTION_MESSAGES[form.status.data], "success")
    return redirect(url_for("inbox.thread_reader", thread_id=thread_id))


def _start_refresh(*, full: bool):
    form = EmptyForm()
    if not form.validate_on_submit():
        abort(400)
    account = current_user.gmail_account
    if account is None:
        return redirect(url_for("accounts.connect_page"))
    # Runs for one account execute serially, so a second import would only queue behind the
    # first and spend the same Gmail quota again.
    existing = active_run(account)
    if existing is not None:
        db.session.commit()
        flash("A refresh is already in progress.", "info")
        return redirect(url_for("inbox.run_status", run_id=existing.id))
    # Without a history checkpoint there is nothing to apply incrementally.
    incremental = not full and bool(account.last_history_id)
    if current_app.config["MAIL_MODE"] == "gmail":
        # This durable run owns the refresh and is reconciled if enqueueing fails. Clear the
        # catch-up flag so periodic reconciliation does not queue a duplicate.
        account.pending_sync = False
        db.session.commit()
    run = create_run(
        current_user,
        account,
        kind="sync" if incremental else "manual",
        limit=current_app.config["INDEX_MAX_THREADS"],
    )
    if current_app.config["MAIL_MODE"] == "fake":
        from mercury.inbox.service import index_account
        from mercury.intelligence.service import analyze_pending

        index_account(account, run, limit=run.requested_limit)
        if account.ai_consent:
            analyze_pending(current_user.id)
    else:
        from mercury.jobs.tasks import enqueue_discovery, enqueue_sync

        queue = current_app.extensions["mercury"]["queue"]
        if incremental:
            enqueue_sync(queue, account, run)
        else:
            enqueue_discovery(queue, account, run)
    return redirect(url_for("inbox.run_status", run_id=run.id))


@bp.post("/app/sync")
@login_required
def sync():
    """Fetch only what changed in Gmail; unchanged threads cost no quota and no AI."""
    return _start_refresh(full=False)


@bp.post("/app/sync/full")
@login_required
def full_rebuild():
    """Development-only full re-index of the lookback window (re-lists every thread)."""
    if current_app.config["APP_ENV"] == "production":
        abort(404)
    return _start_refresh(full=True)


@bp.get("/app/updates")
def updates():
    """Tell an open workspace that new mail or re-organization arrived since it loaded.

    Returns counts only, never content. An expired session gets HTTP 286, which tells htmx to
    stop polling instead of swapping a login page into the banner.
    """
    if not current_user.is_authenticated:
        return "", 286
    try:
        since = datetime.fromtimestamp(int(request.args.get("since", "")), UTC)
    except (OverflowError, OSError, ValueError):
        since = datetime.now(UTC)
    account = current_user.gmail_account
    new_threads = (
        db.session.scalar(
            select(func.count())
            .select_from(EmailThread)
            .where(EmailThread.user_id == current_user.id, EmailThread.latest_message_at > since)
        )
        or 0
    )
    organized = bool(account and account.last_organized_at and account.last_organized_at > since)
    return render_template(
        "inbox/_updates.html",
        since=int(since.timestamp()),
        new_threads=new_threads,
        organized=organized,
    )


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
