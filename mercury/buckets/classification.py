"""Tenant-scoped placement of analyzed threads into existing buckets.

Precedence: a user's manual placement, an exact-sender rule, a sufficiently strong semantic
match, then Unsorted. Manual moves and sender rules are applied elsewhere and are never changed
here; this module only adds, moves, or withdraws Mercury's own ("model") placements. Every write
re-checks that condition in SQL, so a concurrent user move always wins.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from flask import current_app
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert

from mercury.accounts.models import GmailAccount
from mercury.buckets.clustering import conservative_choice, fit_scores, neighbor_scores
from mercury.buckets.models import Bucket, BucketAssignment
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ThreadAnalysis, ThreadEmbedding
from mercury.intelligence.prompts import NORMALIZATION_VERSION

# A bucket needs this many comparable members before new mail is matched against it.
MIN_BUCKET_EXAMPLES = 3

_MOVABLE = (BucketAssignment.origin == "model", BucketAssignment.locked_by_user.is_(False))


@dataclass
class ThreadVector:
    """A plain snapshot, so session commits during naming never reload thousands of rows."""

    thread_id: uuid.UUID
    subject: str
    summary: str
    sender: str | None
    vector: list[float]
    assignment_id: uuid.UUID | None
    assigned_bucket_id: uuid.UUID | None
    origin: str | None
    locked: bool

    @property
    def movable(self) -> bool:
        """Mercury placed this thread itself, so Mercury may place it again."""
        return self.assignment_id is not None and self.origin == "model" and not self.locked

    def bucket_id(self, active: dict[uuid.UUID, Bucket]) -> uuid.UUID | None:
        return self.assigned_bucket_id if self.assigned_bucket_id in active else None

    def unplaced(self, active: dict[uuid.UUID, Bucket]) -> bool:
        # A locked "Unsorted" choice is a placement too; only Mercury's own leftovers qualify.
        return self.assignment_id is None or (self.movable and self.bucket_id(active) is None)


def active_buckets_for(account: GmailAccount) -> dict[uuid.UUID, Bucket]:
    return {
        bucket.id: bucket
        for bucket in db.session.scalars(
            select(Bucket)
            .where(
                Bucket.user_id == account.user_id,
                Bucket.gmail_account_id == account.id,
                Bucket.archived.is_(False),
            )
            .order_by(Bucket.created_at, Bucket.id)
        )
    }


def _sender(participants) -> str | None:
    if not participants:
        return None
    address = str(participants[-1].get("address", "")).strip().casefold()
    return address if "@" in address else None


def load_thread_vectors(account: GmailAccount) -> list[ThreadVector]:
    """Load current, compatible vectors with their placement; never mixes vector pipelines."""
    provider = current_app.extensions["mercury"]["ai_provider"]
    rows = db.session.execute(
        select(
            EmailThread.id,
            EmailThread.subject,
            EmailThread.participants,
            ThreadAnalysis.summary,
            ThreadEmbedding.embedding,
            BucketAssignment.id,
            BucketAssignment.bucket_id,
            BucketAssignment.origin,
            BucketAssignment.locked_by_user,
        )
        .join(
            ThreadAnalysis,
            (ThreadAnalysis.thread_id == EmailThread.id)
            & (ThreadAnalysis.user_id == account.user_id),
        )
        .join(
            ThreadEmbedding,
            (ThreadEmbedding.thread_id == EmailThread.id)
            & (ThreadEmbedding.user_id == account.user_id),
        )
        .outerjoin(
            BucketAssignment,
            (BucketAssignment.thread_id == EmailThread.id)
            & (BucketAssignment.user_id == account.user_id)
            & (BucketAssignment.gmail_account_id == account.id),
        )
        .where(
            EmailThread.user_id == account.user_id,
            EmailThread.gmail_account_id == account.id,
            ThreadAnalysis.stale.is_(False),
            ThreadAnalysis.content_version == EmailThread.content_version,
            ThreadEmbedding.content_version == EmailThread.content_version,
            ThreadEmbedding.provider == provider.name,
            ThreadEmbedding.model == current_app.config["EMBEDDING_MODEL"],
            ThreadEmbedding.dimensions == current_app.config["EMBEDDING_DIMENSIONS"],
            ThreadEmbedding.pipeline_version == NORMALIZATION_VERSION,
        )
        .order_by(EmailThread.latest_message_at.desc(), EmailThread.id)
        .limit(current_app.config["INDEX_MAX_THREADS"])
    ).all()
    return [
        ThreadVector(
            thread_id=thread_id,
            subject=subject,
            summary=summary,
            sender=_sender(participants),
            vector=list(embedding),
            assignment_id=assignment_id,
            assigned_bucket_id=bucket_id,
            origin=origin,
            locked=bool(locked),
        )
        for (
            thread_id,
            subject,
            participants,
            summary,
            embedding,
            assignment_id,
            bucket_id,
            origin,
            locked,
        ) in rows
    ]


def members_by_bucket(
    rows: list[ThreadVector], active: dict[uuid.UUID, Bucket]
) -> dict[uuid.UUID, list[ThreadVector]]:
    grouped: dict[uuid.UUID, list[ThreadVector]] = defaultdict(list)
    for row in rows:
        bucket_id = row.bucket_id(active)
        if bucket_id is not None:
            grouped[bucket_id].append(row)
    return grouped


def place(row: ThreadVector, bucket: Bucket, score: float | None) -> bool:
    """Record a Mercury placement unless a manual or rule placement exists or just appeared."""
    if row.assignment_id is None:
        assignment_id = uuid.uuid4()
        written = db.session.execute(
            insert(BucketAssignment)
            .values(
                id=assignment_id,
                user_id=bucket.user_id,
                gmail_account_id=bucket.gmail_account_id,
                thread_id=row.thread_id,
                bucket_id=bucket.id,
                origin="model",
                score=score,
                locked_by_user=False,
                version=1,
            )
            .on_conflict_do_nothing(index_elements=["thread_id"])
        ).rowcount
    else:
        assignment_id = row.assignment_id
        written = db.session.execute(
            update(BucketAssignment)
            .where(
                BucketAssignment.id == assignment_id,
                BucketAssignment.user_id == bucket.user_id,
                *_MOVABLE,
            )
            .values(bucket_id=bucket.id, score=score, version=BucketAssignment.version + 1)
        ).rowcount
    if written:
        row.assignment_id, row.assigned_bucket_id, row.origin = assignment_id, bucket.id, "model"
    return bool(written)


def move_placements(rows: list[ThreadVector], bucket: Bucket) -> int:
    """Move Mercury's own placements to ``bucket`` in one guarded statement."""
    ids = [row.assignment_id for row in rows if row.movable]
    if not ids:
        return 0
    moved = set(
        db.session.scalars(
            update(BucketAssignment)
            .where(
                BucketAssignment.id.in_(ids),
                BucketAssignment.user_id == bucket.user_id,
                BucketAssignment.gmail_account_id == bucket.gmail_account_id,
                *_MOVABLE,
            )
            .values(bucket_id=bucket.id, version=BucketAssignment.version + 1)
            .returning(BucketAssignment.id)
        )
    )
    for row in rows:
        if row.assignment_id in moved:
            row.assigned_bucket_id = bucket.id
    return len(moved)


def prune_misfits(rows: list[ThreadVector], active: dict[uuid.UUID, Bucket]) -> int:
    """Return Mercury-placed threads that no longer resemble their bucket to Unsorted.

    The keep floor sits below the admit bar, so a thread is not removed and re-added as a
    bucket's membership shifts slightly. Manual and rule placements are never touched.
    """
    keep_min = current_app.config["BUCKET_KEEP_MIN"]
    misfits: list[ThreadVector] = []
    for members in members_by_bucket(rows, active).values():
        if len(members) <= MIN_BUCKET_EXAMPLES:
            continue
        scores = fit_scores([row.vector for row in members])
        loose = [
            row
            for row, score in zip(members, scores, strict=True)
            if row.movable and score < keep_min
        ]
        # Pruning removes a few strays. When most of a bucket misses the bar, the threshold is
        # more likely miscalibrated for this mailbox than the bucket wrong, so leave it intact.
        if len(loose) * 2 <= len(members):
            misfits.extend(loose)
    if not misfits:
        return 0
    removed = set(
        db.session.scalars(
            delete(BucketAssignment)
            .where(BucketAssignment.id.in_([row.assignment_id for row in misfits]), *_MOVABLE)
            .returning(BucketAssignment.id)
        )
    )
    for row in misfits:
        if row.assignment_id in removed:
            row.assignment_id = row.assigned_bucket_id = row.origin = None
    return len(removed)


def classify_unplaced(rows: list[ThreadVector], active: dict[uuid.UUID, Bucket]) -> int:
    """Place each unplaced thread into the one bucket it clearly and strongly resembles."""
    examples = {
        bucket_id: [row.vector for row in members]
        for bucket_id, members in members_by_bucket(rows, active).items()
        if len(members) >= MIN_BUCKET_EXAMPLES
    }
    unplaced = [row for row in rows if row.unplaced(active)]
    if not examples or not unplaced:
        return 0
    queries = [row.vector for row in unplaced]
    # Scores are computed before any placement so one pass does not cascade on itself.
    scores = {
        bucket_id: neighbor_scores(queries, vectors) for bucket_id, vectors in examples.items()
    }
    placed = 0
    for index, row in enumerate(unplaced):
        choice = conservative_choice(
            [(str(bucket_id), values[index]) for bucket_id, values in scores.items()],
            minimum=current_app.config["BUCKET_MATCH_MIN"],
            margin=current_app.config["BUCKET_MATCH_MARGIN"],
        )
        if choice is not None:
            bucket_id = uuid.UUID(choice)
            placed += place(row, active[bucket_id], scores[bucket_id][index])
    return placed
