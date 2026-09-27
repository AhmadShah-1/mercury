"""Bounded, tenant-scoped discovery, splitting, and naming of Mercury's bucket suggestions."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from flask import current_app
from sqlalchemy import update

from mercury.accounts.models import GmailAccount
from mercury.buckets.classification import (
    MIN_BUCKET_EXAMPLES,
    ThreadVector,
    active_buckets_for,
    load_thread_vectors,
    members_by_bucket,
    move_placements,
    place,
)
from mercury.buckets.clustering import (
    centroid_similarity,
    discover_clusters,
    fit_scores,
    representative_indices,
)
from mercury.buckets.models import Bucket
from mercury.buckets.service import unique_bucket_name
from mercury.extensions import db
from mercury.integrations.types import BucketSuggestion
from mercury.intelligence.budget import (
    BudgetExceeded,
    cancel_reservation,
    finish_reservation,
    reserve_bucket_naming,
)

MIN_CLUSTER_SIZE = 8
MIN_SENDER_GROUP_SIZE = 4
# Naming calls per pass for buckets whose meaning has drifted; each one is budgeted.
MAX_RENAMES_PER_PASS = 5
# A bucket's meaning is refreshed once it has grown by half (and at least a cluster's worth).
MEANING_GROWTH_FACTOR = 1.5


def organization_enabled(account: GmailAccount) -> bool:
    return (
        account.ai_consent
        and account.connection_state == "connected"
        and current_app.config["AI_PROCESSING_ENABLED"]
    )


def _still_current(account: GmailAccount, generation: int) -> bool:
    """Re-read the account after a slow provider call; a disconnect stops all writes."""
    db.session.refresh(account)
    return account.connection_state == "connected" and account.connection_generation == generation


def _clean(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


def _suggest_meaning(account: GmailAccount, members: list[ThreadVector]) -> BucketSuggestion:
    """One budgeted naming call over representative members; raises ``BudgetExceeded``."""
    indices = representative_indices([member.vector for member in members], limit=5)
    descriptions = tuple(
        f"Subject: {members[index].subject[:240]}\nSummary: {members[index].summary[:600]}"
        for index in indices
    )
    usage = reserve_bucket_naming(
        user_id=account.user_id,
        estimated_input_tokens=max(1, (sum(len(item) for item in descriptions) + 800) // 4),
        estimated_output_tokens=100,
    )
    provider = current_app.extensions["mercury"]["ai_provider"]
    try:
        suggestion = provider.suggest_bucket(descriptions=descriptions)
    except Exception:
        cancel_reservation(usage.id)
        raise
    finish_reservation(
        usage.id,
        input_tokens=suggestion.input_tokens,
        output_tokens=suggestion.output_tokens,
        embedding_tokens=0,
    )
    return suggestion


def _tight(
    members: list[ThreadVector], minimum_size: int
) -> list[tuple[ThreadVector, float]] | None:
    """Keep only members that closely resemble the rest of their group, or nothing at all.

    Clustering alone admits loosely attached threads; the same bar used for new mail keeps
    outliers in Unsorted instead of inside an otherwise coherent bucket.
    """
    if len(members) < minimum_size:
        return None
    match_min = current_app.config["BUCKET_MATCH_MIN"]
    kept = [
        (member, score)
        for member, score in zip(members, fit_scores([m.vector for m in members]), strict=True)
        if score >= match_min
    ]
    return kept if len(kept) >= minimum_size else None


def _new_bucket(
    account: GmailAccount,
    suggestion: BucketSuggestion,
    *,
    member_count: int,
    split_from: uuid.UUID | None = None,
) -> Bucket:
    ai_name, ai_purpose = _clean(suggestion.name, 80), _clean(suggestion.purpose, 240)
    bucket = Bucket(
        user_id=account.user_id,
        gmail_account_id=account.id,
        name=unique_bucket_name(account.id, ai_name),
        purpose=ai_purpose,
        origin="suggested",
        user_confirmed=False,
        ai_name=ai_name,
        ai_purpose=ai_purpose,
        ai_named_at=datetime.now(UTC),
        named_member_count=member_count,
        reviewed_member_count=member_count,
        split_from_id=split_from,
    )
    db.session.add(bucket)
    db.session.flush()
    return bucket


def _groups(candidates: list[ThreadVector]) -> list[tuple[list[ThreadVector], int]]:
    """Semantic clusters, then exact-sender groups from the noise, each with its minimum size."""
    labels = discover_clusters(
        [candidate.vector for candidate in candidates], min_cluster_size=MIN_CLUSTER_SIZE
    )
    clustered: dict[int, list[ThreadVector]] = defaultdict(list)
    noise: list[ThreadVector] = []
    for candidate, label in zip(candidates, labels, strict=True):
        if label < 0:
            noise.append(candidate)
        else:
            clustered[label].append(candidate)

    # A repeated exact sender is a conservative fallback for useful groups that remain noise.
    by_sender: dict[str, list[ThreadVector]] = defaultdict(list)
    for candidate in noise:
        if candidate.sender:
            by_sender[candidate.sender].append(candidate)
    groups = [(items, MIN_CLUSTER_SIZE) for items in clustered.values()]
    groups.extend(
        (items, MIN_SENDER_GROUP_SIZE)
        for items in by_sender.values()
        if len(items) >= MIN_SENDER_GROUP_SIZE
    )
    return sorted(
        groups,
        key=lambda group: (-len(group[0]), min(str(item.thread_id) for item in group[0])),
    )


def discover_suggested_buckets(
    account: GmailAccount,
    rows: list[ThreadVector] | None = None,
    active: dict[uuid.UUID, Bucket] | None = None,
) -> int:
    """Suggest new buckets from unplaced threads without moving any existing placement."""
    if not organization_enabled(account):
        return 0
    generation = account.connection_generation
    if rows is None or active is None:
        rows, active = load_thread_vectors(account), active_buckets_for(account)
    # MAX_SUGGESTED_BUCKETS bounds one pass (a manageable onboarding set); the active ceiling
    # bounds the whole taxonomy while still letting new topics appear as mail arrives.
    remaining = min(
        current_app.config["MAX_SUGGESTED_BUCKETS"],
        current_app.config["MAX_ACTIVE_BUCKETS"] - len(active),
    )
    candidates = [row for row in rows if row.unplaced(active)]
    if remaining <= 0 or len(candidates) < MIN_SENDER_GROUP_SIZE:
        return 0

    created = 0
    for members, minimum_size in _groups(candidates):
        if created >= remaining:
            break
        kept = _tight(members, minimum_size)
        if kept is None:
            continue
        try:
            suggestion = _suggest_meaning(account, [member for member, _ in kept])
        except BudgetExceeded:
            break
        if not _still_current(account, generation):
            return created
        bucket = _new_bucket(account, suggestion, member_count=len(kept))
        for member, score in kept:
            place(member, bucket, score)
        active[bucket.id] = bucket
        db.session.commit()
        created += 1
    return created


def split_buckets(
    account: GmailAccount, rows: list[ThreadVector], active: dict[uuid.UUID, Bucket]
) -> int:
    """Split a bucket whose members have separated into clearly distinct topics.

    Only buckets that grew since their last check are re-clustered. The part holding the most
    manual and rule placements keeps the bucket's identity and name; only Mercury's own
    placements move to the new bucket. Buckets produced by a user merge are never split.
    """
    generation = account.connection_generation
    created = 0
    grouped = members_by_bucket(rows, active)
    for bucket_id, members in sorted(grouped.items(), key=lambda item: -len(item[1])):
        bucket = active[bucket_id]
        count = len(members)
        reviewed = bucket.reviewed_member_count
        if bucket.merged_at is not None or count < 2 * MIN_CLUSTER_SIZE:
            continue
        if reviewed and count < reviewed + max(MIN_CLUSTER_SIZE, reviewed // 4):
            continue
        bucket.reviewed_member_count = count
        labels = discover_clusters([m.vector for m in members], min_cluster_size=MIN_CLUSTER_SIZE)
        clusters: dict[int, list[ThreadVector]] = defaultdict(list)
        for member, label in zip(members, labels, strict=True):
            if label >= 0:
                clusters[label].append(member)
        parts = sorted(
            (part for part in clusters.values() if len(part) >= MIN_CLUSTER_SIZE),
            key=lambda part: (
                -sum(not member.movable for member in part),
                -len(part),
                min(str(member.thread_id) for member in part),
            ),
        )
        if len(parts) < 2:
            db.session.commit()
            continue
        keeper = [member.vector for member in parts[0]]
        for part in parts[1:]:
            if len(active) >= current_app.config["MAX_ACTIVE_BUCKETS"]:
                break
            separation = centroid_similarity(keeper, [member.vector for member in part])
            if separation > current_app.config["BUCKET_SPLIT_MAX_SIMILARITY"]:
                continue
            kept = _tight([member for member in part if member.movable], MIN_CLUSTER_SIZE)
            if kept is None:
                continue
            try:
                suggestion = _suggest_meaning(account, [member for member, _ in kept])
            except BudgetExceeded:
                db.session.commit()
                return created
            if not _still_current(account, generation):
                return created
            child = _new_bucket(account, suggestion, member_count=len(kept), split_from=bucket.id)
            moved = move_placements([member for member, _ in kept], child)
            active[child.id] = child
            bucket.reviewed_member_count -= moved
            bucket.meaning_stale = True
            db.session.commit()
            created += 1
        db.session.commit()
    return created


def _meaning_due(bucket: Bucket, count: int) -> bool:
    if bucket.meaning_stale or bucket.ai_name is None:
        return True
    named = bucket.named_member_count
    return bool(named) and count >= max(named * MEANING_GROWTH_FACTOR, named + MIN_CLUSTER_SIZE)


def refresh_meanings(
    account: GmailAccount, rows: list[ThreadVector], active: dict[uuid.UUID, Bucket]
) -> int:
    """Update Mercury's meaning for buckets that were split, merged, created, or have grown.

    The display name follows only while the user has not renamed the bucket; a user's name is
    never replaced, and the change is surfaced as "meaning updated" instead.
    """
    generation = account.connection_generation
    grouped = members_by_bucket(rows, active)
    renamed = 0
    for bucket_id, bucket in list(active.items()):
        members = grouped.get(bucket_id, [])
        if len(members) < MIN_BUCKET_EXAMPLES:
            continue
        if bucket.ai_name and not bucket.named_member_count and not bucket.meaning_stale:
            # Named before sizes were tracked: adopt today's size as the baseline.
            bucket.named_member_count = len(members)
            db.session.commit()
            continue
        if not _meaning_due(bucket, len(members)):
            continue
        if renamed >= MAX_RENAMES_PER_PASS:
            break
        try:
            suggestion = _suggest_meaning(account, members)
        except BudgetExceeded:
            break
        if not _still_current(account, generation):
            return renamed
        ai_name, ai_purpose = _clean(suggestion.name, 80), _clean(suggestion.purpose, 240)
        bucket.ai_name, bucket.ai_purpose = ai_name, ai_purpose
        bucket.ai_named_at = datetime.now(UTC)
        bucket.named_member_count = len(members)
        bucket.meaning_stale = False
        # Guarded in SQL so a rename submitted during the naming call is never overwritten.
        db.session.execute(
            update(Bucket)
            .where(Bucket.id == bucket.id, Bucket.user_confirmed.is_(False))
            .values(
                name=unique_bucket_name(account.id, ai_name, exclude=bucket.id), purpose=ai_purpose
            )
        )
        db.session.commit()
        renamed += 1
    return renamed
