from sqlalchemy import select

from mercury.accounts.models import GmailAccount
from mercury.buckets.models import Bucket, BucketAssignment
from mercury.buckets.service import save_sender_rule
from mercury.extensions import db
from mercury.inbox.models import EmailThread
from mercury.inbox.service import upsert_provider_thread
from mercury.integrations.fake_gmail import FakeGmailProvider


def test_sender_rule_precedes_model_but_never_overrides_manual_lock(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        thread = db.session.scalar(
            select(EmailThread).where(EmailThread.gmail_thread_id == "fixture-work-review")
        )
        assignment = db.session.scalar(
            select(BucketAssignment).where(BucketAssignment.thread_id == thread.id)
        )
        destination = db.session.scalar(
            select(Bucket).where(
                Bucket.user_id == account.user_id, Bucket.id != assignment.bucket_id
            )
        )
        original_bucket_id = assignment.bucket_id
        save_sender_rule(
            account.user_id,
            account.id,
            "Mina Patel <MINA@northstar.invalid>",
            destination.id,
        )
        provider_thread = FakeGmailProvider().get_thread("fixture-work-review")

        assignment.locked_by_user = True
        db.session.commit()
        upsert_provider_thread(account, provider_thread)
        db.session.commit()
        db.session.refresh(assignment)
        assert assignment.bucket_id == original_bucket_id

        assignment.locked_by_user = False
        db.session.commit()
        upsert_provider_thread(account, provider_thread)
        db.session.commit()
        db.session.refresh(assignment)
        assert assignment.bucket_id == destination.id
        assert assignment.origin == "rule"
