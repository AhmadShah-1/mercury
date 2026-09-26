from __future__ import annotations

from authlib.integrations.base_client.errors import OAuthError
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from mercury.accounts.forms import (
    ConfirmDeleteForm,
    ConnectForm,
    DevLoginForm,
    EmptyForm,
    LabelSyncForm,
)
from mercury.accounts.service import (
    connect_fake_mailbox,
    delete_user_account,
    disconnect_account,
    get_or_create_demo_user,
)
from mercury.buckets.service import seed_demo_buckets
from mercury.extensions import db
from mercury.inbox.service import create_run, index_account
from mercury.integrations.google.oauth import (
    GMAIL_MODIFY_SCOPE,
    connect_google_account,
    consume_attempt,
    exchange_token,
    start_flow,
    user_from_identity,
)
from mercury.intelligence.service import analyze_pending

bp = Blueprint("accounts", __name__)


@bp.route("/auth/dev", methods=["GET", "POST"])
def dev_login():
    if current_app.config["AUTH_MODE"] != "dev" or current_app.config["APP_ENV"] == "production":
        abort(404)
    form = DevLoginForm()
    if form.validate_on_submit():
        user = get_or_create_demo_user(form.email.data)
        session.clear()
        login_user(user, remember=False, fresh=True)
        session["session_generation"] = str(user.session_generation)
        return redirect(url_for("inbox.workspace"))
    return render_template("accounts/dev_login.html", form=form)


@bp.post("/auth/google/start")
def google_start():
    if current_app.config["AUTH_MODE"] != "google":
        abort(404)
    return start_flow(purpose="login", user=None)


@bp.get("/auth/google/callback")
def google_callback():
    session.pop("google_oauth_purpose", None)
    try:
        attempt = consume_attempt(purpose="login")
        user = user_from_identity(exchange_token(attempt))
    except (OAuthError, ValueError):
        abort(400)
    session.clear()
    login_user(user, remember=False, fresh=True)
    session["session_generation"] = str(user.session_generation)
    return redirect(attempt.return_path)


@bp.route("/auth/gmail/connect", methods=["GET"])
@login_required
def connect_page():
    return render_template("accounts/connect.html", form=ConnectForm())


@bp.post("/auth/gmail/start")
@login_required
def gmail_start():
    form = ConnectForm()
    if not form.validate_on_submit():
        return render_template("accounts/connect.html", form=form), 400
    if current_app.config["MAIL_MODE"] == "fake":
        account = connect_fake_mailbox(current_user, ai_consent=form.ai_consent.data)
        run = create_run(current_user, account, kind="initial", limit=50)
        # The bounded fixture import is synchronous so a fresh demo is immediately usable.
        # Real Gmail is always deferred to the worker.
        index_account(account, run, limit=run.requested_limit)
        if account.ai_consent:
            analyze_pending(current_user.id, onboarding=True)
        seed_demo_buckets(account)
        flash("Synthetic mailbox connected.", "success")
        return redirect(url_for("inbox.workspace"))
    session["gmail_ai_consent"] = bool(form.ai_consent.data)
    return start_flow(purpose="gmail", user=current_user)


@bp.get("/auth/gmail/callback")
@login_required
def gmail_callback():
    purpose = session.pop("google_oauth_purpose", "gmail")
    if purpose not in {"gmail", "gmail_modify"}:
        abort(400)
    try:
        attempt = consume_attempt(purpose=purpose)
    except ValueError:
        abort(400)
    if attempt.user_id != current_user.id:
        abort(404)
    try:
        account = connect_google_account(current_user, exchange_token(attempt))
    except (OAuthError, ValueError):
        abort(400)
    if purpose == "gmail_modify":
        if GMAIL_MODIFY_SCOPE not in account.granted_scopes:
            abort(403)
        account.label_write_consent = True
        db.session.commit()
        flash("Gmail label synchronization is enabled.", "success")
        return redirect(url_for("accounts.settings"))
    account.ai_consent = bool(session.pop("gmail_ai_consent", False))
    run = create_run(
        current_user, account, kind="initial", limit=current_app.config["INDEX_MAX_THREADS"]
    )
    from mercury.jobs.tasks import enqueue_discovery

    enqueue_discovery(current_app.extensions["mercury"]["queue"], account, run)
    return redirect(url_for("inbox.run_status", run_id=run.id))


@bp.post("/auth/logout")
@login_required
def logout():
    form = EmptyForm()
    if not form.validate_on_submit():
        abort(400)
    logout_user()
    session.clear()
    return redirect(url_for("public.index"))


@bp.get("/settings")
@login_required
def settings():
    return _render_settings(ConfirmDeleteForm())


def _label_sync_counts() -> dict[str, int]:
    """Owner-scoped label mapping status counts for display; no mailbox content."""
    from sqlalchemy import func, select

    from mercury.buckets.models import GmailLabelMapping

    rows = db.session.execute(
        select(GmailLabelMapping.sync_status, func.count())
        .where(GmailLabelMapping.user_id == current_user.id)
        .group_by(GmailLabelMapping.sync_status)
    ).all()
    return {status: count for status, count in rows}


def _render_settings(delete_form, status: int = 200):
    label_form = LabelSyncForm()
    if current_user.gmail_account:
        label_form.enabled.data = current_user.gmail_account.label_write_consent
    return render_template(
        "accounts/settings.html",
        disconnect_form=EmptyForm(),
        delete_form=delete_form,
        label_form=label_form,
        label_counts=_label_sync_counts() if current_user.gmail_account else {},
    ), status


@bp.post("/settings/labels")
@login_required
def label_settings():
    form = LabelSyncForm()
    if not form.validate_on_submit():
        abort(400)
    account = current_user.gmail_account
    if account is None:
        abort(404)
    if not form.enabled.data:
        account.label_write_consent = False
        db.session.commit()
        flash("Gmail label synchronization is disabled.", "success")
        return redirect(url_for("accounts.settings"))
    if not current_app.config["GMAIL_LABEL_WRITES_ENABLED"]:
        abort(403)
    if current_app.config["MAIL_MODE"] != "gmail":
        abort(409)
    if GMAIL_MODIFY_SCOPE in account.granted_scopes:
        account.label_write_consent = True
        db.session.commit()
        return redirect(url_for("accounts.settings"))
    return start_flow(purpose="gmail_modify", user=current_user, gmail_modify=True)


@bp.post("/settings/disconnect")
@login_required
def disconnect():
    form = EmptyForm()
    if not form.validate_on_submit():
        abort(400)
    disconnect_account(current_user)
    logout_user()
    session.clear()
    flash("Gmail was disconnected and Mercury's derived mailbox data was removed.", "success")
    return redirect(url_for("public.index"))


@bp.post("/settings/delete")
@login_required
def delete_account():
    form = ConfirmDeleteForm()
    if not form.validate_on_submit() or form.confirmation.data != "DELETE":
        flash("Type DELETE exactly to confirm.", "danger")
        return _render_settings(form, 400)
    delete_user_account(current_user)
    logout_user()
    session.clear()
    return redirect(url_for("public.index"))
