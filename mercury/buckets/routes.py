from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from mercury.accounts.forms import EmptyForm
from mercury.buckets.crates import (
    active_crates,
    build_library,
    combine_crates,
    create_crate,
    dissolve_crate,
    owned_crate,
    place_bucket,
    rename_crate,
    set_bucket_favorite,
    set_crate_favorite,
    unsorted_size,
)
from mercury.buckets.forms import (
    BucketForm,
    CombineCratesForm,
    FavoriteForm,
    NewCrateForm,
    PlaceBucketForm,
    RenameCrateForm,
    SenderRuleForm,
)
from mercury.buckets.models import SenderRule
from mercury.buckets.service import (
    active_buckets,
    archive_bucket,
    create_bucket,
    follow_ai_name,
    owned_bucket,
    rename_bucket,
    save_sender_rule,
)
from mercury.extensions import db

bp = Blueprint("buckets", __name__)


def _next_url(default: str) -> str:
    """Return the posted ``next`` only when it is a local Mercury path; never an external URL."""
    target = request.form.get("next", "")
    parts = urlsplit(target)
    if (
        target.startswith("/app")
        and not parts.scheme
        and not parts.netloc
        and "\\" not in target
        and target.isprintable()
    ):
        return target
    return default


def _done(message: str, default: str):
    # Drag-and-drop requests say so and show their own notice; answering 204 (never a
    # redirect) lets the script tell a saved change from a redirect to the sign-in page.
    if request.headers.get("X-Mercury-Quiet") == "1":
        return "", 204
    flash(message, "success")
    return redirect(_next_url(default), code=303)


def _library(**selected):
    return build_library(
        current_user.id,
        buckets=active_buckets(current_user.id),
        unsorted_count=unsorted_size(current_user.id),
        **selected,
    )


@bp.route("/app/buckets/new", methods=["GET", "POST"])
@login_required
def create():
    account = current_user.gmail_account
    if account is None:
        return redirect(url_for("accounts.connect_page"))
    form = BucketForm()
    if form.validate_on_submit():
        bucket = create_bucket(current_user.id, account.id, form.name.data, form.purpose.data)
        return redirect(url_for("inbox.bucket_workspace", bucket_id=bucket.id))
    return render_template("buckets/edit.html", form=form, title="Create bucket")


@bp.route("/app/buckets/<uuid:bucket_id>/edit", methods=["GET", "POST"])
@login_required
def edit(bucket_id):
    bucket = owned_bucket(current_user.id, bucket_id)
    if bucket is None:
        abort(404)
    form = BucketForm(obj=bucket)
    if form.validate_on_submit():
        rename_bucket(current_user.id, bucket.id, form.name.data, form.purpose.data)
        return redirect(url_for("inbox.bucket_workspace", bucket_id=bucket.id))
    return render_template(
        "buckets/edit.html",
        form=form,
        title="Edit bucket",
        bucket=bucket,
        library=_library(selected_bucket=bucket),
        next_path=url_for("buckets.edit", bucket_id=bucket.id),
    )


@bp.post("/app/buckets/<uuid:bucket_id>/follow-ai-name")
@login_required
def follow_ai(bucket_id):
    form = EmptyForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        follow_ai_name(current_user.id, bucket_id)
    except LookupError:
        abort(404)
    except ValueError:
        abort(409)
    flash("This bucket now uses Mercury's name and will follow future updates.", "success")
    return redirect(url_for("inbox.bucket_workspace", bucket_id=bucket_id))


@bp.post("/app/buckets/<uuid:bucket_id>/archive")
@login_required
def archive(bucket_id):
    form = EmptyForm()
    if not form.validate_on_submit():
        abort(400)
    archive_bucket(current_user.id, bucket_id)
    return redirect(url_for("inbox.workspace"))


@bp.get("/app/organize")
@login_required
def organize():
    """The Edit view: only crates and buckets, arranged by dragging or with plain forms."""
    if current_user.gmail_account is None:
        return redirect(url_for("accounts.connect_page"))
    return render_template(
        "buckets/organize.html", library=_library(), next_path=url_for("buckets.organize")
    )


@bp.post("/app/buckets/<uuid:bucket_id>/crate")
@login_required
def place(bucket_id):
    bucket = owned_bucket(current_user.id, bucket_id)
    if bucket is None or bucket.archived:
        abort(404)
    form = PlaceBucketForm()
    form.crate_id.choices = [("", "No crate"), ("new", "New crate")] + [
        (str(crate.id), crate.name) for crate in active_crates(current_user.id)
    ]
    form.with_bucket_id.choices = [("", "")] + [
        (str(item.id), item.name) for item in active_buckets(current_user.id)
    ]
    if not form.validate_on_submit():
        abort(400)
    try:
        if form.crate_id.data == "new":
            # Dropping one bucket onto another starts a crate of the two, wherever they were.
            other = uuid.UUID(form.with_bucket_id.data) if form.with_bucket_id.data else None
            if other == bucket.id:
                abort(409)
            crate = create_crate(
                current_user.id, [other, bucket.id] if other else [bucket.id], form.name.data
            )
        else:
            crate_id = uuid.UUID(form.crate_id.data) if form.crate_id.data else None
            place_bucket(
                current_user.id, bucket.id, crate_id, restore_auto=form.restore.data == "auto"
            )
            crate = owned_crate(current_user.id, crate_id) if crate_id else None
    except LookupError:
        abort(404)
    except ValueError:
        abort(409)
    message = (
        f"{bucket.name} is now in {crate.name}." if crate else f"{bucket.name} left its crate."
    )
    return _done(message, url_for("buckets.organize"))


@bp.post("/app/buckets/<uuid:bucket_id>/favorite")
@login_required
def favorite(bucket_id):
    form = FavoriteForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        bucket = set_bucket_favorite(current_user.id, bucket_id, form.favorite.data == "1")
    except LookupError:
        abort(404)
    state = "added to" if bucket.favorite else "removed from"
    return _done(
        f"{bucket.name} {state} favorites.",
        url_for("inbox.bucket_workspace", bucket_id=bucket.id),
    )


@bp.post("/app/crates")
@login_required
def crate_create():
    form = NewCrateForm()
    form.bucket_ids.choices = [
        (str(item.id), item.name) for item in active_buckets(current_user.id)
    ]
    if not form.validate_on_submit():
        abort(400)
    try:
        crate = create_crate(
            current_user.id, [uuid.UUID(value) for value in form.bucket_ids.data], form.name.data
        )
    except LookupError:
        abort(404)
    except ValueError:
        abort(409)
    return _done(f"Created the crate {crate.name}.", url_for("buckets.organize"))


@bp.post("/app/crates/<uuid:crate_id>/rename")
@login_required
def crate_rename(crate_id):
    form = RenameCrateForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        crate = rename_crate(current_user.id, crate_id, form.name.data)
    except LookupError:
        abort(404)
    except ValueError:
        abort(400)
    return _done(f"Renamed the crate to {crate.name}.", url_for("buckets.organize"))


@bp.post("/app/crates/<uuid:crate_id>/favorite")
@login_required
def crate_favorite(crate_id):
    form = FavoriteForm()
    if not form.validate_on_submit():
        abort(400)
    try:
        crate = set_crate_favorite(current_user.id, crate_id, form.favorite.data == "1")
    except LookupError:
        abort(404)
    state = "added to" if crate.favorite else "removed from"
    return _done(
        f"{crate.name} {state} favorites.",
        url_for("inbox.crate_workspace", crate_id=crate.id),
    )


@bp.post("/app/crates/<uuid:crate_id>/dissolve")
@login_required
def crate_dissolve(crate_id):
    form = EmptyForm()
    if not form.validate_on_submit():
        abort(400)
    crate = owned_crate(current_user.id, crate_id)
    if crate is None:
        abort(404)
    name, kept = crate.name, crate.is_misc
    released = dissolve_crate(current_user.id, crate.id)
    noun = "bucket" if released == 1 else "buckets"
    message = (
        f"Took {released} {noun} out of {name}."
        if kept
        else f"Unpacked {name}; its {released} {noun} are back on their own."
    )
    return _done(message, url_for("buckets.organize"))


@bp.post("/app/crates/<uuid:crate_id>/combine")
@login_required
def crate_combine(crate_id):
    source = owned_crate(current_user.id, crate_id)
    if source is None:
        abort(404)
    form = CombineCratesForm()
    form.target_id.choices = [
        (str(crate.id), crate.name) for crate in active_crates(current_user.id)
    ]
    if not form.validate_on_submit():
        abort(400)
    source_name = source.name
    try:
        combine_crates(current_user.id, source.id, uuid.UUID(form.target_id.data))
    except LookupError:
        abort(404)
    except ValueError:
        abort(409)
    target = owned_crate(current_user.id, uuid.UUID(form.target_id.data))
    return _done(
        f"Moved everything in {source_name} into {target.name}.", url_for("buckets.organize")
    )


@bp.route("/app/rules", methods=["GET", "POST"])
@login_required
def rules():
    account = current_user.gmail_account
    if account is None:
        abort(404)
    choices = [(str(item.id), item.name) for item in active_buckets(current_user.id)]
    form = SenderRuleForm()
    form.bucket_id.choices = choices
    if form.validate_on_submit():
        save_sender_rule(
            current_user.id, account.id, form.sender_address.data, uuid.UUID(form.bucket_id.data)
        )
        return redirect(url_for("buckets.rules"))
    rows = db.session.scalars(
        select(SenderRule)
        .where(SenderRule.user_id == current_user.id)
        .order_by(SenderRule.sender_address)
    ).all()
    return render_template("buckets/rules.html", form=form, rules=rows)
