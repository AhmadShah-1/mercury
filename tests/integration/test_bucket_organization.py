"""Automatic organization: filing new mail, pruning misfits, splitting, merging, and naming."""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import delete, select

from mercury.accounts.models import GmailAccount
from mercury.buckets.models import Bucket, BucketAssignment
from mercury.buckets.organize import organize_account
from mercury.buckets.service import merge_buckets, rename_bucket
from mercury.extensions import db
from tests.bucket_vectors import add_thread, assign, bucket_of, make_bucket, near, topic

JOBS, LOANS, RECEIPTS = topic(101), topic(202), topic(303)


@pytest.fixture
def account(app, connected):
    with app.app_context():
        # Start from an empty taxonomy; fixture threads keep their unrelated fake vectors.
        db.session.execute(delete(BucketAssignment))
        db.session.execute(delete(Bucket))
        db.session.commit()
        yield db.session.scalar(select(GmailAccount))


def _populate(account, bucket, direction, count, *, seed, origin="model", subject=None):
    rng = np.random.default_rng(seed)
    ids = []
    for _ in range(count):
        thread_id = add_thread(
            account, near(direction, rng), subject=subject or f"{bucket.name} update"
        )
        assign(account, thread_id, bucket, origin=origin)
        ids.append(thread_id)
    return ids


def test_new_mail_is_filed_into_the_bucket_it_clearly_matches(app, account, monkeypatch):
    # A lower admit bar makes the ambiguous thread below fail on margin, not on similarity.
    monkeypatch.setitem(app.config, "BUCKET_MATCH_MIN", 0.55)
    monkeypatch.setitem(app.config, "BUCKET_KEEP_MIN", 0.50)
    jobs = make_bucket(account, "Job Opportunities")
    loans = make_bucket(account, "Student Loans")
    _populate(account, jobs, JOBS, 5, seed=1)
    _populate(account, loans, LOANS, 5, seed=2)
    rng = np.random.default_rng(3)
    job_mail = add_thread(account, near(JOBS, rng))
    loan_mail = add_thread(account, near(LOANS, rng))
    unrelated = add_thread(account, near(RECEIPTS, rng))
    # Halfway between two buckets is ambiguous: similar enough to both, clearly closer to none.
    between = (JOBS + LOANS) / np.linalg.norm(JOBS + LOANS)
    ambiguous = add_thread(account, near(between, rng, spread=0.2))

    counts = organize_account(account)

    assert counts["placed"] == 2
    assert bucket_of(job_mail) == jobs.id
    assert bucket_of(loan_mail) == loans.id
    assert bucket_of(unrelated) is None
    assert bucket_of(ambiguous) is None
    assert db.session.get(GmailAccount, account.id).last_organized_at is not None


def test_misfit_model_placements_return_to_unsorted_but_manual_and_rule_ones_stay(account):
    jobs = make_bucket(account, "Job Opportunities")
    _populate(account, jobs, JOBS, 6, seed=4)
    rng = np.random.default_rng(5)
    stray_model = add_thread(account, near(RECEIPTS, rng))
    stray_manual = add_thread(account, near(RECEIPTS, rng))
    stray_rule = add_thread(account, near(LOANS, rng))
    assign(account, stray_model, jobs)
    assign(account, stray_manual, jobs, origin="user")
    assign(account, stray_rule, jobs, origin="rule")

    counts = organize_account(account)

    assert counts["pruned"] == 1
    assert bucket_of(stray_model) is None
    assert bucket_of(stray_manual) == jobs.id
    assert bucket_of(stray_rule) == jobs.id


def test_future_mail_follows_a_merge_by_id_even_after_renaming(account):
    jobs = make_bucket(account, "Job Opportunities")
    loans = make_bucket(account, "Student Loan Offers")
    _populate(account, jobs, JOBS, 5, seed=6)
    _populate(account, loans, LOANS, 5, seed=7)

    merge_buckets(account.user_id, jobs.id, loans.id)
    rename_bucket(account.user_id, loans.id, "Career and Finance", "")
    new_job_mail = add_thread(account, near(JOBS, np.random.default_rng(8)))
    organize_account(account)

    destination = db.session.get(Bucket, loans.id)
    assert bucket_of(new_job_mail) == loans.id
    assert db.session.get(Bucket, jobs.id).archived is True
    assert destination.name == "Career and Finance"
    assert destination.merged_at is not None


def test_bucket_splits_when_members_separate_and_manual_placements_stay(account):
    mixed = make_bucket(account, "Opportunities", ai_name="Opportunities")
    manual_jobs = _populate(account, mixed, JOBS, 3, seed=9, origin="user")
    _populate(account, mixed, JOBS, 9, seed=10)
    loans = _populate(account, mixed, LOANS, 12, seed=11, subject="Statement payment due")

    counts = organize_account(account)

    assert counts["split"] == 1
    child = db.session.scalar(select(Bucket).where(Bucket.split_from_id == mixed.id))
    assert child is not None and child.origin == "suggested"
    assert child.ai_name == "Financial Notices"
    assert {bucket_of(thread_id) for thread_id in loans} == {child.id}
    # The part holding the user's own placements keeps the original bucket and name.
    assert {bucket_of(thread_id) for thread_id in manual_jobs} == {mixed.id}
    parent = db.session.get(Bucket, mixed.id)
    assert parent.meaning_stale is False and parent.ai_named_at is not None


def test_merged_buckets_are_not_split_back_apart(account):
    jobs = make_bucket(account, "Job Opportunities")
    loans = make_bucket(account, "Student Loan Offers")
    _populate(account, jobs, JOBS, 12, seed=12)
    _populate(account, loans, LOANS, 12, seed=13)
    merge_buckets(account.user_id, jobs.id, loans.id)

    counts = organize_account(account)

    assert counts["split"] == 0
    assert db.session.scalar(select(Bucket).where(Bucket.split_from_id == loans.id)) is None


def test_display_name_follows_mercury_until_the_user_renames(account):
    following = make_bucket(account, "Old Meaning", meaning_stale=True)
    _populate(account, following, JOBS, 4, seed=14, subject="Project review request")
    renamed = make_bucket(account, "My Receipts", meaning_stale=True)
    _populate(account, renamed, RECEIPTS, 4, seed=15, subject="Your order has shipped")
    rename_bucket(account.user_id, renamed.id, "My Receipts", "")

    counts = organize_account(account)

    assert counts["renamed"] == 2
    following = db.session.get(Bucket, following.id)
    assert (following.name, following.ai_name) == ("Projects and Reviews", "Projects and Reviews")
    assert following.meaning_updated is False
    renamed = db.session.get(Bucket, renamed.id)
    assert (renamed.name, renamed.ai_name) == ("My Receipts", "Orders and Deliveries")
    assert renamed.meaning_updated is True


def test_new_topics_become_suggestions_without_loose_members(account, monkeypatch):
    from mercury.buckets import discovery

    monkeypatch.setattr(
        discovery, "discover_clusters", lambda vectors, **_kwargs: [0] * len(vectors)
    )
    rng = np.random.default_rng(16)
    core = [add_thread(account, near(RECEIPTS, rng), subject="Order shipped") for _ in range(9)]
    loose = [add_thread(account, near(JOBS, rng)) for _ in range(2)]

    counts = organize_account(account)

    assert counts["suggested"] == 1
    bucket = db.session.scalar(select(Bucket).where(Bucket.ai_name == "Orders and Deliveries"))
    assert {bucket_of(thread_id) for thread_id in core} == {bucket.id}
    assert [bucket_of(thread_id) for thread_id in loose] == [None, None]


def test_organization_is_skipped_without_ai_consent(account):
    jobs = make_bucket(account, "Job Opportunities")
    _populate(account, jobs, JOBS, 5, seed=17)
    new_mail = add_thread(account, near(JOBS, np.random.default_rng(18)))
    account.ai_consent = False
    db.session.commit()

    assert not any(organize_account(account).values())
    assert bucket_of(new_mail) is None


def test_a_mostly_loose_bucket_is_left_intact_rather_than_emptied(account):
    loose = make_bucket(account, "Mixed Bag")
    rng = np.random.default_rng(19)
    members = [add_thread(account, near(topic(400 + index), rng)) for index in range(6)]
    for thread_id in members:
        assign(account, thread_id, loose)

    assert organize_account(account)["pruned"] == 0
    assert {bucket_of(thread_id) for thread_id in members} == {loose.id}


def test_bucket_scores_command_reports_numbers_only(app, account):
    jobs = make_bucket(account, "Job Opportunities")
    _populate(account, jobs, JOBS, 5, seed=20, subject="Confidential offer letter")
    add_thread(account, near(JOBS, np.random.default_rng(21)), subject="Confidential offer")

    result = app.test_cli_runner().invoke(args=["bucket-scores", "alex@example.invalid"])

    assert result.exit_code == 0, result.output
    assert "Job Opportunities" in result.output
    assert "would_place=1" in result.output
    assert "Confidential" not in result.output


def test_an_unusable_bucket_name_skips_that_bucket_without_failing_the_pass(account, monkeypatch):
    from mercury.integrations.ai.fake import FakeAIProvider
    from mercury.integrations.types import InvalidProviderOutput

    def refuse(self, *, descriptions):
        raise InvalidProviderOutput("invalid_structured_output")

    monkeypatch.setattr(FakeAIProvider, "suggest_bucket", refuse)
    stale = make_bucket(account, "Job Opportunities", meaning_stale=True)
    _populate(account, stale, JOBS, 5, seed=22)
    new_mail = add_thread(account, near(JOBS, np.random.default_rng(23)))

    counts = organize_account(account)

    assert counts["placed"] == 1 and counts["renamed"] == 0
    assert bucket_of(new_mail) == stale.id
    stale = db.session.get(Bucket, stale.id)
    assert (stale.name, stale.meaning_stale, stale.named_member_count) == (
        "Job Opportunities",
        False,
        6,
    )
