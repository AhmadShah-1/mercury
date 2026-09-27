"""Keep an account's buckets current as analyzed mail arrives.

One pass runs in the worker after analysis, under the account lock:

1. withdraw Mercury placements that no longer resemble their bucket;
2. split buckets whose members have separated into distinct topics;
3. file unplaced threads into the one bucket each clearly matches;
4. suggest new buckets from what is still unplaced;
5. refresh Mercury's meaning for buckets that were created, split, merged, or have grown.

Only unplaced threads and buckets that grew are clustered; the whole mailbox never is. Manual
moves and sender rules are never changed. The pass needs no AI calls except bucket naming,
because it reuses the embeddings analysis already stored.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mercury.accounts.models import GmailAccount
from mercury.buckets.classification import (
    active_buckets_for,
    classify_unplaced,
    load_thread_vectors,
    prune_misfits,
)
from mercury.buckets.discovery import (
    discover_suggested_buckets,
    organization_enabled,
    refresh_meanings,
    split_buckets,
)
from mercury.extensions import db


def organize_account(account: GmailAccount) -> dict[str, int]:
    counts = dict.fromkeys(("pruned", "split", "placed", "suggested", "renamed"), 0)
    if not organization_enabled(account):
        return counts
    rows = load_thread_vectors(account)
    active = active_buckets_for(account)
    counts["pruned"] = prune_misfits(rows, active)
    db.session.commit()
    counts["split"] = split_buckets(account, rows, active)
    counts["placed"] = classify_unplaced(rows, active)
    db.session.commit()
    counts["suggested"] = discover_suggested_buckets(account, rows, active)
    counts["renamed"] = refresh_meanings(account, rows, active)
    if any(counts.values()):
        account.last_organized_at = datetime.now(UTC)
        db.session.commit()
    return counts
