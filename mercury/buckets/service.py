from __future__ import annotations

import unicodedata
import uuid
from email.utils import parseaddr

from sqlalchemy import func, select, update

from mercury.accounts.models import GmailAccount
from mercury.buckets.models import Bucket, BucketAssignment, SenderRule
from mercury.extensions import db
from mercury.inbox.models import EmailThread


def active_buckets(user_id: uuid.UUID) -> list[Bucket]:
    return list(
        db.session.scalars(
            select(Bucket)
            .where(Bucket.user_id == user_id, Bucket.archived.is_(False))
            .order_by(Bucket.name)
        )
    )


def create_bucket(
    user_id: uuid.UUID, account_id: uuid.UUID, name: str, purpose: str = ""
) -> Bucket:
    clean = " ".join(name.split())[:80]
    if not clean:
        raise ValueError("bucket name is required")
    bucket = Bucket(
        user_id=user_id,
        gmail_account_id=account_id,
        name=clean,
        purpose=" ".join(purpose.split())[:240],
    )
    db.session.add(bucket)
    db.session.commit()
    return bucket


def owned_bucket(user_id: uuid.UUID, bucket_id: uuid.UUID) -> Bucket | None:
    return db.session.scalar(
        select(Bucket).where(Bucket.id == bucket_id, Bucket.user_id == user_id)
    )


def move_thread(user_id: uuid.UUID, thread_id: uuid.UUID, bucket_id: uuid.UUID | None) -> None:
    thread = db.session.scalar(
        select(EmailThread).where(EmailThread.id == thread_id, EmailThread.user_id == user_id)
    )
    if thread is None:
        raise LookupError("thread_not_found")
    bucket = owned_bucket(user_id, bucket_id) if bucket_id else None
    if bucket_id and (bucket is None or bucket.gmail_account_id != thread.gmail_account_id):
        raise LookupError("bucket_not_found")
    assignment = db.session.scalar(
        select(BucketAssignment).where(BucketAssignment.thread_id == thread.id)
    )
    if assignment is None:
        assignment = BucketAssignment(
            user_id=user_id,
            gmail_account_id=thread.gmail_account_id,
            thread_id=thread.id,
        )
        db.session.add(assignment)
    assignment.bucket_id = bucket.id if bucket else None
    assignment.origin = "user"
    assignment.locked_by_user = True
    assignment.version += 1
    db.session.commit()


def rename_bucket(user_id: uuid.UUID, bucket_id: uuid.UUID, name: str, purpose: str) -> None:
    bucket = owned_bucket(user_id, bucket_id)
    if bucket is None:
        raise LookupError("bucket_not_found")
    clean = " ".join(name.split())[:80]
    if not clean:
        raise ValueError("bucket name is required")
    bucket.name = clean
    bucket.purpose = " ".join(purpose.split())[:240]
    bucket.user_confirmed = True
    db.session.commit()


def archive_bucket(user_id: uuid.UUID, bucket_id: uuid.UUID) -> None:
    bucket = owned_bucket(user_id, bucket_id)
    if bucket is None:
        raise LookupError("bucket_not_found")
    bucket.archived = True
    db.session.commit()


def merge_preview_count(user_id: uuid.UUID, source_id: uuid.UUID) -> int:
    if owned_bucket(user_id, source_id) is None:
        raise LookupError("bucket_not_found")
    return (
        db.session.scalar(
            select(func.count())
            .select_from(BucketAssignment)
            .where(BucketAssignment.user_id == user_id, BucketAssignment.bucket_id == source_id)
        )
        or 0
    )


def merge_buckets(user_id: uuid.UUID, source_id: uuid.UUID, destination_id: uuid.UUID) -> None:
    source = owned_bucket(user_id, source_id)
    destination = owned_bucket(user_id, destination_id)
    if (
        source is None
        or destination is None
        or source.gmail_account_id != destination.gmail_account_id
    ):
        raise LookupError("bucket_not_found")
    if source.id == destination.id:
        raise ValueError("a bucket cannot be merged into itself")
    db.session.execute(
        update(BucketAssignment)
        .where(BucketAssignment.user_id == user_id, BucketAssignment.bucket_id == source.id)
        .values(bucket_id=destination.id, version=BucketAssignment.version + 1)
    )
    db.session.execute(
        update(SenderRule)
        .where(SenderRule.user_id == user_id, SenderRule.bucket_id == source.id)
        .values(bucket_id=destination.id)
    )
    source.archived = True
    db.session.commit()


def normalize_sender(value: str) -> str:
    _, address = parseaddr(value)
    address = unicodedata.normalize("NFKC", address).strip().casefold()
    if "@" not in address or len(address) > 320:
        raise ValueError("enter a valid exact sender address")
    return address


def save_sender_rule(
    user_id: uuid.UUID, account_id: uuid.UUID, sender: str, bucket_id: uuid.UUID
) -> None:
    bucket = owned_bucket(user_id, bucket_id)
    if bucket is None or bucket.gmail_account_id != account_id:
        raise LookupError("bucket_not_found")
    address = normalize_sender(sender)
    rule = db.session.scalar(
        select(SenderRule).where(
            SenderRule.gmail_account_id == account_id, SenderRule.sender_address == address
        )
    )
    if rule is None:
        rule = SenderRule(
            user_id=user_id,
            gmail_account_id=account_id,
            sender_address=address,
            bucket_id=bucket_id,
        )
        db.session.add(rule)
    else:
        rule.bucket_id = bucket_id
        rule.enabled = True
    db.session.commit()


def seed_demo_buckets(account: GmailAccount) -> None:
    if db.session.scalar(
        select(func.count()).select_from(Bucket).where(Bucket.user_id == account.user_id)
    ):
        return
    mapping = {
        "fixture-work-review": ("Work", "Projects and work conversations"),
        "fixture-shopping": ("Purchases", "Orders and purchase updates"),
        "fixture-bank-html": ("Finance", "Statements and financial notices"),
        "fixture-newsletter": ("Newsletters", "News and recurring reading"),
    }
    buckets: dict[str, Bucket] = {}
    for name, purpose in set(mapping.values()):
        bucket = Bucket(
            user_id=account.user_id,
            gmail_account_id=account.id,
            name=name,
            purpose=purpose,
            origin="suggested",
            user_confirmed=False,
        )
        db.session.add(bucket)
        db.session.flush()
        buckets[name] = bucket
    for provider_id, (name, _) in mapping.items():
        thread = db.session.scalar(
            select(EmailThread).where(
                EmailThread.gmail_account_id == account.id,
                EmailThread.gmail_thread_id == provider_id,
            )
        )
        if thread:
            db.session.add(
                BucketAssignment(
                    user_id=account.user_id,
                    gmail_account_id=account.id,
                    thread_id=thread.id,
                    bucket_id=buckets[name].id,
                    origin="model",
                    score=0.9,
                )
            )
    db.session.commit()
