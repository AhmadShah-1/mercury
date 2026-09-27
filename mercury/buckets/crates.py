"""Crates: user-arranged groups of buckets, plus each account's default Misc crate.

A crate gathers buckets for navigation only. Every thread stays assigned to exactly one bucket, so
grouping, regrouping, and ungrouping never change a placement, a sender rule, a Gmail label, or
the examples Mercury classifies new mail against. Crates hold buckets, never other crates.

Mercury itself only files its own small suggested buckets into Misc, and takes each back out once
it grows. A bucket the user created or placed is never moved automatically.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from mercury.accounts.models import GmailAccount
from mercury.buckets.models import Bucket, BucketAssignment, Crate
from mercury.buckets.service import owned_bucket
from mercury.extensions import db

MISC_NAME = "Misc"
# Mercury's own buckets with fewer conversations than this are filed into Misc.
MISC_MAX_MEMBERS = 15
# Without favorites, a sidebar section shows this many of its largest items.
NAV_FALLBACK_SIZE = 3
DEFAULT_CRATE_NAME = "New crate"


def owned_crate(user_id: uuid.UUID, crate_id: uuid.UUID) -> Crate | None:
    return db.session.scalar(select(Crate).where(Crate.id == crate_id, Crate.user_id == user_id))


def active_crates(user_id: uuid.UUID) -> list[Crate]:
    crates = db.session.scalars(select(Crate).where(Crate.user_id == user_id)).all()
    return sorted(crates, key=lambda crate: (crate.is_misc, crate.name.casefold()))


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())[:80]


def unique_crate_name(
    account_id: uuid.UUID, proposed: str, *, exclude: uuid.UUID | None = None
) -> str:
    """Return ``proposed`` or a numbered variant unused by the account's other crates."""
    base = _clean(proposed) or DEFAULT_CRATE_NAME
    query = select(Crate.name).where(Crate.gmail_account_id == account_id)
    if exclude is not None:
        query = query.where(Crate.id != exclude)
    existing = {name.casefold() for name in db.session.scalars(query)}
    if base.casefold() not in existing:
        return base
    for suffix in range(2, 100):
        candidate = f"{base[:74].rstrip()} ({suffix})"
        if candidate.casefold() not in existing:
            return candidate
    raise ValueError("crate_name_exhausted")


def _misc_crate(account_id: uuid.UUID) -> Crate | None:
    return db.session.scalar(
        select(Crate).where(Crate.gmail_account_id == account_id, Crate.kind == "misc")
    )


def ensure_misc_crate(account: GmailAccount) -> Crate:
    """Return the account's Misc crate, creating it once. Safe to call repeatedly."""
    misc = _misc_crate(account.id)
    if misc is not None:
        return misc
    # The partial unique index makes a concurrent creation a no-op instead of a duplicate.
    db.session.execute(
        insert(Crate)
        .values(
            id=uuid.uuid4(),
            user_id=account.user_id,
            gmail_account_id=account.id,
            name=unique_crate_name(account.id, MISC_NAME),
            kind="misc",
            favorite=False,
        )
        .on_conflict_do_nothing()
    )
    db.session.commit()
    misc = _misc_crate(account.id)
    if misc is None:
        raise RuntimeError("misc_crate_unavailable")
    return misc


def _owned_active_bucket(user_id: uuid.UUID, bucket_id: uuid.UUID) -> Bucket:
    bucket = owned_bucket(user_id, bucket_id)
    if bucket is None or bucket.archived:
        raise LookupError("bucket_not_found")
    return bucket


def release_if_empty(user_id: uuid.UUID, crate_id: uuid.UUID | None) -> bool:
    """Delete a user crate that no longer holds an active bucket. Misc always stays."""
    if crate_id is None:
        return False
    crate = owned_crate(user_id, crate_id)
    if crate is None or crate.is_misc:
        return False
    db.session.flush()
    active = db.session.scalar(
        select(func.count())
        .select_from(Bucket)
        .where(
            Bucket.user_id == user_id,
            Bucket.crate_id == crate.id,
            Bucket.archived.is_(False),
        )
    )
    if active:
        return False
    db.session.execute(
        update(Bucket)
        .where(Bucket.user_id == user_id, Bucket.crate_id == crate.id)
        .values(crate_id=None)
        .execution_options(synchronize_session=False)
    )
    db.session.delete(crate)
    return True


def place_bucket(
    user_id: uuid.UUID,
    bucket_id: uuid.UUID,
    crate_id: uuid.UUID | None,
    *,
    restore_auto: bool = False,
) -> Bucket:
    """Put a bucket in a crate (or in none) as the user's own choice, which Mercury keeps.

    Choosing the crate a bucket is already in changes nothing, so Mercury's own Misc filing is
    not silently turned into a user placement. ``restore_auto`` undoes a move of a bucket
    Mercury had filed, handing it back to automatic filing; it applies only to Mercury's own
    suggestions going back to Misc or to no crate.
    """
    bucket = _owned_active_bucket(user_id, bucket_id)
    crate = owned_crate(user_id, crate_id) if crate_id else None
    if crate_id and (crate is None or crate.gmail_account_id != bucket.gmail_account_id):
        raise LookupError("crate_not_found")
    if restore_auto and (bucket.origin != "suggested" or (crate is not None and not crate.is_misc)):
        raise ValueError("only Mercury's own filing can be restored")
    previous = bucket.crate_id
    target = crate.id if crate else None
    if previous == target and not restore_auto:
        return bucket
    bucket.crate_id = target
    bucket.crate_origin = "auto" if restore_auto else "user"
    if previous != target:
        release_if_empty(user_id, previous)
    db.session.commit()
    return bucket


def _default_name(buckets: list[Bucket]) -> str:
    if len(buckets) == 2:
        joined = f"{buckets[0].name} & {buckets[1].name}"
        if len(joined) <= 80:
            return joined
    return DEFAULT_CRATE_NAME


def create_crate(user_id: uuid.UUID, bucket_ids: list[uuid.UUID], name: str = "") -> Crate:
    """Gather one or more of the user's buckets into a new crate."""
    unique_ids = list(dict.fromkeys(bucket_ids))
    if not unique_ids:
        raise ValueError("a crate needs at least one bucket")
    buckets = [_owned_active_bucket(user_id, bucket_id) for bucket_id in unique_ids]
    account_id = buckets[0].gmail_account_id
    if any(bucket.gmail_account_id != account_id for bucket in buckets):
        raise LookupError("bucket_not_found")
    crate = Crate(
        user_id=user_id,
        gmail_account_id=account_id,
        name=unique_crate_name(account_id, _clean(name) or _default_name(buckets)),
        kind="user",
    )
    db.session.add(crate)
    db.session.flush()
    previous = {bucket.crate_id for bucket in buckets} - {None}
    for bucket in buckets:
        bucket.crate_id = crate.id
        bucket.crate_origin = "user"
    for crate_id in previous:
        release_if_empty(user_id, crate_id)
    db.session.commit()
    return crate


def rename_crate(user_id: uuid.UUID, crate_id: uuid.UUID, name: str) -> Crate:
    crate = owned_crate(user_id, crate_id)
    if crate is None:
        raise LookupError("crate_not_found")
    clean = _clean(name)
    if not clean:
        raise ValueError("crate name is required")
    crate.name = unique_crate_name(crate.gmail_account_id, clean, exclude=crate.id)
    db.session.commit()
    return crate


def set_crate_favorite(user_id: uuid.UUID, crate_id: uuid.UUID, favorite: bool) -> Crate:
    crate = owned_crate(user_id, crate_id)
    if crate is None:
        raise LookupError("crate_not_found")
    crate.favorite = favorite
    db.session.commit()
    return crate


def set_bucket_favorite(user_id: uuid.UUID, bucket_id: uuid.UUID, favorite: bool) -> Bucket:
    """Favoriting a bucket is independent of its crate's favorite, in both directions."""
    bucket = _owned_active_bucket(user_id, bucket_id)
    bucket.favorite = favorite
    db.session.commit()
    return bucket


def dissolve_crate(user_id: uuid.UUID, crate_id: uuid.UUID) -> int:
    """Take every bucket out of a crate and delete it; Misc is only emptied."""
    crate = owned_crate(user_id, crate_id)
    if crate is None:
        raise LookupError("crate_not_found")
    released = db.session.execute(
        update(Bucket)
        .where(Bucket.user_id == user_id, Bucket.crate_id == crate.id)
        .values(crate_id=None, crate_origin="user")
        .execution_options(synchronize_session=False)
    ).rowcount
    if not crate.is_misc:
        db.session.delete(crate)
    db.session.commit()
    return released


def combine_crates(user_id: uuid.UUID, source_id: uuid.UUID, target_id: uuid.UUID) -> int:
    """Move every bucket of one crate into another; the emptied source goes (Misc stays)."""
    source = owned_crate(user_id, source_id)
    target = owned_crate(user_id, target_id)
    if source is None or target is None or source.gmail_account_id != target.gmail_account_id:
        raise LookupError("crate_not_found")
    if source.id == target.id:
        raise ValueError("a crate cannot be combined with itself")
    combined = db.session.execute(
        update(Bucket)
        .where(
            Bucket.user_id == user_id,
            Bucket.crate_id == source.id,
            Bucket.archived.is_(False),
        )
        .values(crate_id=target.id, crate_origin="user")
        .execution_options(synchronize_session=False)
    ).rowcount
    release_if_empty(user_id, source.id)
    db.session.commit()
    return combined


def bucket_sizes(user_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Conversation count per bucket for one owner; counts only, never content."""
    return dict(
        db.session.execute(
            select(BucketAssignment.bucket_id, func.count())
            .where(BucketAssignment.user_id == user_id, BucketAssignment.bucket_id.is_not(None))
            .group_by(BucketAssignment.bucket_id)
        ).all()
    )


def file_small_buckets(account: GmailAccount) -> int:
    """File Mercury's small suggested buckets into Misc and graduate grown ones back out.

    Each suggested bucket is judged once, when it first appears. One that started in Misc leaves
    once it reaches ``MISC_MAX_MEMBERS`` and is not filed again if it later shrinks. The SQL
    guards let a placement the user made in the meantime win over this pass.
    """
    misc = ensure_misc_crate(account)
    sizes = bucket_sizes(account.user_id)
    candidates = db.session.scalars(
        select(Bucket).where(
            Bucket.user_id == account.user_id,
            Bucket.gmail_account_id == account.id,
            Bucket.origin == "suggested",
            Bucket.archived.is_(False),
            (Bucket.crate_origin.is_(None))
            | ((Bucket.crate_origin == "auto") & (Bucket.crate_id == misc.id)),
        )
    ).all()
    moved = 0
    for bucket in candidates:
        small = sizes.get(bucket.id, 0) < MISC_MAX_MEMBERS
        if bucket.crate_origin is None:
            # Judged once: a small bucket goes into Misc, a larger one stays where it is.
            values = {"crate_origin": "auto", **({"crate_id": misc.id} if small else {})}
            guard = Bucket.crate_origin.is_(None)
        elif not small:
            values = {"crate_id": None}
            guard = (Bucket.crate_origin == "auto") & (Bucket.crate_id == misc.id)
        else:
            continue
        result = db.session.execute(
            update(Bucket)
            .where(Bucket.id == bucket.id, guard)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if "crate_id" in values:
            moved += result.rowcount
    db.session.commit()
    return moved


@dataclass
class Library:
    """Everything the sidebar and the Organize view show about crates and buckets."""

    crates: list[Crate]
    buckets: list[Bucket]
    members: dict[uuid.UUID, list[Bucket]]
    crate_of: dict[uuid.UUID, Crate]
    loose: list[Bucket]
    bucket_size: dict[uuid.UUID, int]
    crate_size: dict[uuid.UUID, int]
    nav_crates: list[Crate] = field(default_factory=list)
    nav_buckets: list[Bucket] = field(default_factory=list)
    crates_pinned: bool = False
    buckets_pinned: bool = False
    expanded_crate_id: uuid.UUID | None = None
    hidden_count: int = 0
    misc_threshold: int = MISC_MAX_MEMBERS


def build_library(
    user_id: uuid.UUID,
    *,
    buckets: list[Bucket],
    sizes: dict[uuid.UUID, int] | None = None,
    selected_bucket: Bucket | None = None,
    selected_crate: Crate | None = None,
) -> Library:
    """Arrange the owner's crates and active buckets for display.

    Each sidebar section shows its favorites, or its largest few until something of that kind
    is favorited. Favoriting a crate never favorites its buckets. The selected crate (or the
    crate holding the selected bucket) is always shown, expanded, so the current view is visible.
    """
    crates = active_crates(user_id)
    sizes = bucket_sizes(user_id) if sizes is None else sizes
    members: dict[uuid.UUID, list[Bucket]] = {crate.id: [] for crate in crates}
    crate_by_id = {crate.id: crate for crate in crates}
    crate_of: dict[uuid.UUID, Crate] = {}
    loose: list[Bucket] = []
    for bucket in buckets:
        crate = crate_by_id.get(bucket.crate_id) if bucket.crate_id else None
        if crate is None:
            loose.append(bucket)
        else:
            members[crate.id].append(bucket)
            crate_of[bucket.id] = crate
    bucket_size = {bucket.id: sizes.get(bucket.id, 0) for bucket in buckets}
    crate_size = {
        crate.id: sum(bucket_size[bucket.id] for bucket in members[crate.id]) for crate in crates
    }
    library = Library(
        crates=crates,
        buckets=buckets,
        members=members,
        crate_of=crate_of,
        loose=loose,
        bucket_size=bucket_size,
        crate_size=crate_size,
    )

    favorite_crates = [crate for crate in crates if crate.favorite]
    library.crates_pinned = bool(favorite_crates)
    library.nav_crates = (
        favorite_crates
        or sorted(
            (crate for crate in crates if members[crate.id]),
            key=lambda crate: (-crate_size[crate.id], crate.name.casefold()),
        )[:NAV_FALLBACK_SIZE]
    )
    favorite_buckets = [bucket for bucket in buckets if bucket.favorite]
    library.buckets_pinned = bool(favorite_buckets)
    library.nav_buckets = (
        favorite_buckets
        or sorted(buckets, key=lambda bucket: (-bucket_size[bucket.id], bucket.name.casefold()))[
            :NAV_FALLBACK_SIZE
        ]
    )

    expanded = selected_crate or (crate_of.get(selected_bucket.id) if selected_bucket else None)
    if expanded is not None:
        library.expanded_crate_id = expanded.id
        if all(crate.id != expanded.id for crate in library.nav_crates):
            library.nav_crates.append(expanded)
    if (
        selected_bucket is not None
        and selected_bucket.id in bucket_size
        and selected_bucket.id not in crate_of
        and all(bucket.id != selected_bucket.id for bucket in library.nav_buckets)
    ):
        library.nav_buckets.append(selected_bucket)
    library.hidden_count = max(0, len(crates) - len(library.nav_crates)) + max(
        0, len(buckets) - len(library.nav_buckets)
    )
    return library
