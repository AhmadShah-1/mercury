"""Narrow, ownership-checked writer for labels created and recorded by Mercury."""

from __future__ import annotations

import re
import uuid

from flask import current_app
from sqlalchemy import select

from mercury.accounts.models import GmailAccount
from mercury.buckets.models import Bucket, BucketAssignment, GmailLabelMapping
from mercury.extensions import db
from mercury.inbox.models import EmailThread
from mercury.integrations.google.oauth import GMAIL_MODIFY_SCOPE


class LabelWriteDenied(RuntimeError):
    pass


def _label_name(bucket: Bucket) -> str:
    clean = re.sub(r"[\x00-\x1f\x7f]", "", bucket.name).strip().replace("/", "-")
    return f"{current_app.config['GMAIL_LABEL_PREFIX']}/{clean}"[:225]


def apply_owned_label(
    *,
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    bucket_id: uuid.UUID | None,
    connection_generation: int,
) -> None:
    account = db.session.scalar(
        select(GmailAccount).where(
            GmailAccount.id == account_id,
            GmailAccount.user_id == user_id,
        )
    )
    thread = db.session.scalar(
        select(EmailThread).where(
            EmailThread.id == thread_id,
            EmailThread.user_id == user_id,
            EmailThread.gmail_account_id == account_id,
        )
    )
    bucket = (
        db.session.scalar(
            select(Bucket).where(
                Bucket.id == bucket_id,
                Bucket.user_id == user_id,
                Bucket.gmail_account_id == account_id,
            )
        )
        if bucket_id is not None
        else None
    )
    assignment_query = select(BucketAssignment).where(
        BucketAssignment.thread_id == thread_id,
        BucketAssignment.user_id == user_id,
        BucketAssignment.gmail_account_id == account_id,
    )
    assignment_query = assignment_query.where(
        BucketAssignment.bucket_id == bucket_id
        if bucket_id is not None
        else BucketAssignment.bucket_id.is_(None)
    )
    assignment = db.session.scalar(assignment_query)
    if (
        account is None
        or thread is None
        or assignment is None
        or (bucket_id is not None and bucket is None)
    ):
        raise LookupError("label_target_not_found")
    if (
        not current_app.config["GMAIL_LABEL_WRITES_ENABLED"]
        or current_app.config["MAIL_MODE"] != "gmail"
        or not account.label_write_consent
        or GMAIL_MODIFY_SCOPE not in account.granted_scopes
        or account.connection_state != "connected"
        or account.connection_generation != connection_generation
    ):
        raise LabelWriteDenied("label_write_not_enabled")

    provider = current_app.extensions["mercury"]["mail_provider"](account)
    if bucket is None:
        # Unsorted is deliberately not a Gmail label. Moving here only removes labels that
        # Mercury created and recorded; user-created labels are never listed or touched.
        owned_ids = list(
            db.session.scalars(
                select(GmailLabelMapping.gmail_label_id).where(
                    GmailLabelMapping.gmail_account_id == account_id,
                    GmailLabelMapping.user_id == user_id,
                )
            )
        )
        db.session.refresh(account)
        if account.connection_generation != connection_generation:
            raise LabelWriteDenied("stale_connection_generation")
        provider.apply_label(thread.gmail_thread_id, add=[], remove=owned_ids)
        return

    mapping = db.session.scalar(
        select(GmailLabelMapping).where(
            GmailLabelMapping.bucket_id == bucket.id,
            GmailLabelMapping.user_id == user_id,
            GmailLabelMapping.gmail_account_id == account_id,
        )
    )
    if mapping is None:
        desired_name = _label_name(bucket)
        label_id = provider.create_label(desired_name)
        db.session.refresh(account)
        if account.connection_generation != connection_generation:
            raise LabelWriteDenied("stale_connection_generation")
        mapping = GmailLabelMapping(
            user_id=user_id,
            gmail_account_id=account_id,
            bucket_id=bucket.id,
            gmail_label_id=label_id,
            desired_name=desired_name,
            sync_status="pending",
        )
        db.session.add(mapping)
        db.session.commit()

    other_owned_ids = list(
        db.session.scalars(
            select(GmailLabelMapping.gmail_label_id).where(
                GmailLabelMapping.gmail_account_id == account_id,
                GmailLabelMapping.user_id == user_id,
                GmailLabelMapping.bucket_id != bucket.id,
            )
        )
    )
    db.session.refresh(account)
    if account.connection_generation != connection_generation:
        raise LabelWriteDenied("stale_connection_generation")
    provider.apply_label(
        thread.gmail_thread_id,
        add=[mapping.gmail_label_id],
        remove=other_owned_ids,
    )
    mapping.sync_status = "synced"
    db.session.commit()
