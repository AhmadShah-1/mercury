from __future__ import annotations

import uuid

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import select

from mercury.accounts.forms import EmptyForm
from mercury.buckets.forms import BucketForm, MergeForm, SenderRuleForm
from mercury.buckets.models import SenderRule
from mercury.buckets.service import (
    active_buckets,
    archive_bucket,
    create_bucket,
    merge_buckets,
    merge_preview_count,
    owned_bucket,
    rename_bucket,
    save_sender_rule,
)
from mercury.extensions import db

bp = Blueprint("buckets", __name__)


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
    return render_template("buckets/edit.html", form=form, title="Edit bucket", bucket=bucket)


@bp.post("/app/buckets/<uuid:bucket_id>/archive")
@login_required
def archive(bucket_id):
    form = EmptyForm()
    if not form.validate_on_submit():
        abort(400)
    archive_bucket(current_user.id, bucket_id)
    return redirect(url_for("inbox.workspace"))


@bp.route("/app/buckets/<uuid:bucket_id>/merge", methods=["GET", "POST"])
@login_required
def merge(bucket_id):
    source = owned_bucket(current_user.id, bucket_id)
    if source is None:
        abort(404)
    choices = [
        (str(item.id), item.name)
        for item in active_buckets(current_user.id)
        if item.id != source.id
    ]
    form = MergeForm()
    form.destination_id.choices = choices
    affected = merge_preview_count(current_user.id, source.id)
    if form.validate_on_submit():
        merge_buckets(current_user.id, source.id, uuid.UUID(form.destination_id.data))
        flash(f"Merged {affected} thread assignments.", "success")
        return redirect(url_for("inbox.workspace"))
    return render_template("buckets/merge.html", form=form, source=source, affected=affected)


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
