from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.pool import NullPool

from mercury.accounts.models import GmailAccount
from mercury.extensions import db
from mercury.inbox.models import EmailThread, MessageReference, ThreadAnalysis
from mercury.inbox.sync import account_lock, sync_account_history
from mercury.integrations.fake_gmail import FakeGmailProvider
from mercury.integrations.types import ProviderMessage


class HistoryProvider(FakeGmailProvider):
    def __init__(self):
        self.history_calls: list[str | None] = []
        self.add_message = False

    def list_history(self, start_history_id: str, page_token: str | None = None) -> dict:
        self.history_calls.append(page_token)
        if page_token is None:
            return {
                "history": [{"labelsAdded": [{"message": {"threadId": "fixture-work-review"}}]}],
                "nextPageToken": "page-2",
                "historyId": "1001",
            }
        return {
            "history": [{"labelsRemoved": [{"message": {"threadId": "fixture-work-review"}}]}],
            "historyId": "1002",
        }

    def get_thread_metadata(self, thread_id: str):
        thread = super().get_thread(thread_id)
        first = replace(thread.messages[0], labels=("INBOX", "STARRED"))
        messages = (first,)
        if self.add_message:
            messages += (
                ProviderMessage(
                    id="msg-work-new",
                    internet_message_id="<msg-work-new@fixtures.invalid>",
                    sender_name="Mina Patel",
                    sender_address="mina@northstar.invalid",
                    recipients=("alex@example.invalid",),
                    sent_at=datetime(2026, 9, 25, 12, tzinfo=UTC),
                    labels=("INBOX", "UNREAD"),
                    mime_type="text/plain",
                    body="",
                ),
            )
        return replace(thread, messages=messages, unread=False)


def test_paginated_label_only_history_advances_checkpoint_without_reanalysis(
    app, connected, monkeypatch
):
    provider = HistoryProvider()
    monkeypatch.setitem(app.extensions["mercury"], "mail_provider", lambda account: provider)
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        thread = db.session.scalar(
            select(EmailThread).where(EmailThread.gmail_thread_id == "fixture-work-review")
        )
        original_version = thread.content_version
        original_summary = db.session.scalar(
            select(ThreadAnalysis.summary).where(ThreadAnalysis.thread_id == thread.id)
        )
        sync_account_history(account.id, account.connection_generation)
        db.session.refresh(account)
        db.session.refresh(thread)
        assert provider.history_calls == [None, "page-2"]
        assert account.last_history_id == "1002"
        assert account.pending_sync is False
        assert thread.content_version == original_version
        assert thread.processing_state == "complete"
        assert (
            db.session.scalar(
                select(ThreadAnalysis.summary).where(ThreadAnalysis.thread_id == thread.id)
            )
            == original_summary
        )
        labels = db.session.scalar(
            select(MessageReference.gmail_labels).where(MessageReference.thread_id == thread.id)
        )
        assert labels == ["INBOX", "STARRED"]


def test_new_message_marks_existing_analysis_stale(app, connected, monkeypatch):
    provider = HistoryProvider()
    provider.add_message = True
    monkeypatch.setitem(app.extensions["mercury"], "mail_provider", lambda account: provider)
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        thread = db.session.scalar(
            select(EmailThread).where(EmailThread.gmail_thread_id == "fixture-work-review")
        )
        original_version = thread.content_version
        sync_account_history(account.id, account.connection_generation)
        db.session.refresh(thread)
        analysis = db.session.scalar(
            select(ThreadAnalysis).where(ThreadAnalysis.thread_id == thread.id)
        )
        assert thread.content_version != original_version
        assert thread.processing_state == "pending"
        assert analysis.stale is True


def test_stale_generation_job_returns_before_provider_call(app, connected, monkeypatch):
    provider = HistoryProvider()
    monkeypatch.setitem(app.extensions["mercury"], "mail_provider", lambda account: provider)
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        sync_account_history(account.id, account.connection_generation - 1)
        assert provider.history_calls == []


def _lock_is_free(app, key: str) -> bool:
    """Probe the advisory lock from an independent session, then release any probe hold."""
    engine = create_engine(app.config["SQLALCHEMY_DATABASE_URI"], poolclass=NullPool)
    try:
        with engine.connect() as probe:
            acquired = probe.scalar(text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": key})
            if acquired:
                probe.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": key})
            return bool(acquired)
    finally:
        engine.dispose()


def test_account_lock_survives_commits_and_is_released(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        key = str(account.id)
        with account_lock(account.id):
            db.session.commit()
            # Hold the pooled connection the session just returned so the next ORM statement
            # runs on another one; a lock taken through db.session would be stranded here.
            stranded = db.engine.connect()
            db.session.scalar(select(GmailAccount.id))
            assert not _lock_is_free(app, key)
        try:
            assert _lock_is_free(app, key)
        finally:
            stranded.close()


def test_account_lock_releases_after_failure(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        with pytest.raises(RuntimeError), account_lock(account.id):
            raise RuntimeError("boom")
        assert _lock_is_free(app, str(account.id))


def test_sync_task_keeps_its_run_open_through_analysis_then_completes(app, connected, monkeypatch):
    from types import SimpleNamespace

    from mercury.inbox.models import ProcessingRun
    from mercury.jobs import tasks as task_module

    provider = HistoryProvider()
    monkeypatch.setitem(app.extensions["mercury"], "mail_provider", lambda account: provider)
    seen = []
    analyze = task_module.analyze_pending

    def spy(user_id, **kwargs):
        # Progress polling stops at "succeeded", so the run must still be open here.
        seen.append(db.session.get(ProcessingRun, run_id).status)
        return analyze(user_id, **kwargs)

    monkeypatch.setattr(task_module, "analyze_pending", spy)
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = ProcessingRun(
            user_id=account.user_id, gmail_account_id=account.id, kind="sync", requested_limit=50
        )
        db.session.add(run)
        db.session.commit()
        run_id, account_id, generation = run.id, account.id, account.connection_generation

    task_module.bind_flask_app(app)
    task_module.sync_account_history_task(
        SimpleNamespace(job=None),
        account_id=str(account_id),
        connection_generation=generation,
        run_id=str(run_id),
    )

    with app.app_context():
        run = db.session.get(ProcessingRun, run_id)
        assert seen == ["running"]
        assert (run.status, run.stage, run.found_count) == ("succeeded", "complete", 1)
