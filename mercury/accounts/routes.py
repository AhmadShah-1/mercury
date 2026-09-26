from __future__ import annotations

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

from mercury.accounts.forms import ConfirmDeleteForm, ConnectForm, DevLoginForm, EmptyForm
from mercury.accounts.service import (
    connect_fake_mailbox,
    delete_user_account,
    disconnect_account,
    get_or_create_demo_user,
)
from mercury.buckets.service import seed_demo_buckets
from mercury.inbox.service import create_run, index_account
from mercury.integrations.google.oauth import (
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
    attempt = consume_attempt(purpose="login")
    user = user_from_identity(exchange_token(attempt))
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
            analyze_pending(current_user.id)
        seed_demo_buckets(account)
        flash("Synthetic mailbox connected.", "success")
        return redirect(url_for("inbox.workspace"))
    session["gmail_ai_consent"] = bool(form.ai_consent.data)
    return start_flow(purpose="gmail", user=current_user)


@bp.get("/auth/gmail/callback")
@login_required
def gmail_callback():
    attempt = consume_attempt(purpose="gmail")
    if attempt.user_id != current_user.id:
        abort(404)
    account = connect_google_account(current_user, exchange_token(attempt))
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
    return render_template(
        "accounts/settings.html",
        disconnect_form=EmptyForm(),
        delete_form=ConfirmDeleteForm(),
    )


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
        return render_template(
            "accounts/settings.html", disconnect_form=EmptyForm(), delete_form=form
        ), 400
    delete_user_account(current_user)
    logout_user()
    session.clear()
    return redirect(url_for("public.index"))
