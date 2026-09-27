from __future__ import annotations

import numpy as np
from sqlalchemy import delete, func, select

from mercury.buckets import discovery as discovery_module
from mercury.buckets.discovery import discover_suggested_buckets
from mercury.buckets.models import Bucket, BucketAssignment
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ThreadEmbedding
from mercury.intelligence.models import AIUsage
from tests.bucket_vectors import add_thread, near, topic


def _clear_demo_placements() -> None:
    """Drop demo buckets and give the fixture threads one coherent topic to cluster."""
    db.session.execute(delete(BucketAssignment))
    db.session.execute(delete(Bucket))
    rng = np.random.default_rng(7)
    direction = topic(1)
    for embedding in db.session.scalars(select(ThreadEmbedding).order_by(ThreadEmbedding.id)):
        embedding.embedding = near(direction, rng)
    db.session.commit()


def test_discovery_creates_grounded_suggestion_and_is_idempotent(app, connected, monkeypatch):
    with app.app_context():
        account = db.session.scalar(select(discovery_module.GmailAccount))
        _clear_demo_placements()
        monkeypatch.setattr(
            discovery_module,
            "discover_clusters",
            lambda vectors, **_kwargs: [0] * len(vectors),
        )

        assert discover_suggested_buckets(account) == 1
        bucket = db.session.scalar(select(Bucket))
        assert bucket is not None
        assert bucket.origin == "suggested"
        assert bucket.user_confirmed is False
        assert db.session.scalar(select(func.count()).select_from(BucketAssignment)) == 8
        assert (
            db.session.scalar(
                select(func.count()).select_from(AIUsage).where(AIUsage.category == "bucket-naming")
            )
            == 1
        )

        assert discover_suggested_buckets(account) == 0
        assert db.session.scalar(select(func.count()).select_from(Bucket)) == 1


def test_discovery_preserves_manual_assignment(app, connected, monkeypatch):
    with app.app_context():
        account = db.session.scalar(select(discovery_module.GmailAccount))
        _clear_demo_placements()
        thread = db.session.scalar(select(EmailThread).order_by(EmailThread.id))
        manual = Bucket(
            user_id=account.user_id,
            gmail_account_id=account.id,
            name="My Manual Bucket",
            purpose="A user-owned placement.",
            origin="user",
            user_confirmed=True,
        )
        db.session.add(manual)
        db.session.flush()
        locked = BucketAssignment(
            user_id=account.user_id,
            gmail_account_id=account.id,
            thread_id=thread.id,
            bucket_id=manual.id,
            origin="user",
            locked_by_user=True,
        )
        db.session.add(locked)
        db.session.commit()
        # Keep a full cluster's worth of unplaced threads after the manual placement.
        add_thread(account, near(topic(1), np.random.default_rng(8)))
        monkeypatch.setattr(
            discovery_module,
            "discover_clusters",
            lambda vectors, **_kwargs: [0] * len(vectors),
        )

        assert discover_suggested_buckets(account) == 1
        db.session.refresh(locked)
        assert locked.bucket_id == manual.id
        assert locked.locked_by_user is True
        assert db.session.scalar(select(func.count()).select_from(BucketAssignment)) == 9


def test_discovery_does_not_mix_vector_pipeline_versions(app, connected, monkeypatch):
    with app.app_context():
        account = db.session.scalar(select(discovery_module.GmailAccount))
        _clear_demo_placements()
        embedding = db.session.scalar(select(ThreadEmbedding).order_by(ThreadEmbedding.id))
        embedding.pipeline_version = "retired-pipeline"
        db.session.commit()
        add_thread(account, near(topic(1), np.random.default_rng(8)))
        seen = []

        def cluster(vectors, **_kwargs):
            seen.append(len(vectors))
            return [0] * len(vectors)

        monkeypatch.setattr(discovery_module, "discover_clusters", cluster)
        assert discover_suggested_buckets(account) == 1
        assert seen == [8]
        assert db.session.scalar(select(func.count()).select_from(BucketAssignment)) == 8
