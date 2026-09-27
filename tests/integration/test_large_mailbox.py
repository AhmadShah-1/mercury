"""Behaviour that only shows up past one page or batch: analysis, long runs, and list paging."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text, update

from mercury.accounts.models import GmailAccount
from mercury.extensions import db
from mercury.inbox.models import EmailThread, ProcessingRun
from mercury.intelligence import service as intelligence
from mercury.jobs.tasks import enqueue_discovery, reconcile

HX = {"HX-Request": "true"}


def _states() -> dict[str, int]:
    return dict(
        db.session.execute(
            select(EmailThread.processing_state, func.count()).group_by(
                EmailThread.processing_state
            )
        ).all()
    )


def test_analysis_works_through_every_batch_in_one_call(app, connected, monkeypatch):
    monkeypatch.setattr(intelligence, "ANALYSIS_BATCH_SIZE", 3)
    with app.app_context():
        db.session.execute(update(EmailThread).values(processing_state="pending"))
        db.session.commit()
        user_id = db.session.scalar(select(GmailAccount.user_id))

        intelligence.analyze_pending(user_id)

        assert _states() == {"complete": 8}


def test_analysis_stops_at_the_first_budget_pause(app, connected, monkeypatch):
    monkeypatch.setattr(intelligence, "ANALYSIS_BATCH_SIZE", 3)
    monkeypatch.setitem(app.config, "AI_ACCOUNT_DAILY_THREAD_LIMIT", 2)
    with app.app_context():
        db.session.execute(update(EmailThread).values(processing_state="pending"))
        db.session.commit()
        user_id = db.session.scalar(select(GmailAccount.user_id))

        intelligence.analyze_pending(user_id)

        # The rest resume on the next run instead of each spending a failed reservation.
        assert _states() == {"complete": 2, "budget_paused": 1, "pending": 5}


def test_long_running_import_with_a_live_job_is_not_treated_as_stalled(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = ProcessingRun(
            user_id=account.user_id,
            gmail_account_id=account.id,
            kind="manual",
            requested_limit=1000,
            status="running",
            created_at=datetime.now(UTC) - timedelta(minutes=40),
        )
        db.session.add(run)
        db.session.commit()
        enqueue_discovery(app.extensions["mercury"]["queue"], account, run)
        db.session.execute(text("UPDATE procrastinate_jobs SET status = 'doing'"))
        db.session.commit()

        assert reconcile(app)["recovered"] == 0
        db.session.refresh(run)
        assert (run.status, run.stage) == ("running", "queued")

        # Once no job is queued or executing, the same run is recovered.
        db.session.execute(text("UPDATE procrastinate_jobs SET status = 'failed'"))
        db.session.commit()
        assert reconcile(app)["recovered"] == 1


def test_thread_list_pages_through_every_conversation_once(app, client, connected, monkeypatch):
    monkeypatch.setitem(app.config, "INBOX_PAGE_SIZE", 3)
    with app.app_context():
        expected = set(db.session.scalars(select(EmailThread.id)).all())

    page = client.get("/app?view=all")
    seen = re.findall(r'id="thread-([0-9a-f-]{36})"', page.data.decode())
    more = re.search(r'href="(/app\?[^"]*before=[^"]+)"', page.data.decode())
    pages = 1
    while more:
        chunk = client.get(more.group(1).replace("&amp;", "&"), headers=HX).data.decode()
        assert "<html" not in chunk
        seen += re.findall(r'id="thread-([0-9a-f-]{36})"', chunk)
        more = re.search(r'href="(/app\?[^"]*before=[^"]+)"', chunk)
        pages += 1

    assert pages == 3
    assert len(seen) == len(set(seen)) == 8
    assert {str(thread_id) for thread_id in expected} == set(seen)


def test_invalid_cursor_falls_back_to_the_first_page(client, connected):
    page = client.get("/app?view=all&before=not-a-cursor")
    assert page.status_code == 200
    assert len(re.findall(r'id="thread-', page.data.decode())) == 8


def test_progress_treats_gmail_counts_as_estimates_while_indexing(app, client, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = ProcessingRun(
            user_id=account.user_id,
            gmail_account_id=account.id,
            kind="manual",
            requested_limit=1000,
            status="running",
            stage="indexing",
            found_count=201,
            completed_count=55,
        )
        db.session.add(run)
        db.session.commit()
        run_id = run.id

    early = client.get(f"/app/runs/{run_id}", headers=HX).data.decode()
    assert "55 of about 201 (Gmail's estimate)" in early
    assert "Found 201" not in early

    with app.app_context():
        run = db.session.get(ProcessingRun, run_id)
        run.found_count = run.completed_count = 226
        db.session.commit()
    past = client.get(f"/app/runs/{run_id}", headers=HX).data.decode()
    assert "226 so far · more than Gmail's estimate" in past
    assert 'value="226"' not in past


def test_one_unusable_ai_reply_skips_that_thread_and_the_run_continues(app, connected, monkeypatch):
    from mercury.integrations.ai.fake import FakeAIProvider
    from mercury.integrations.types import InvalidProviderOutput
    from mercury.intelligence.models import AIUsage

    summarize = FakeAIProvider.summarize

    def flaky(self, *, text, message_ids):
        if "forecast" in text.lower():
            raise InvalidProviderOutput("invalid_structured_output")
        return summarize(self, text=text, message_ids=message_ids)

    monkeypatch.setattr(FakeAIProvider, "summarize", flaky)
    monkeypatch.setattr(intelligence, "ANALYSIS_BATCH_SIZE", 3)
    with app.app_context():
        db.session.execute(update(EmailThread).values(processing_state="pending"))
        db.session.commit()
        user_id = db.session.scalar(select(GmailAccount.user_id))

        intelligence.analyze_pending(user_id)

        assert _states() == {"complete": 7, "analysis_failed": 1}
        failed = db.session.scalar(
            select(func.count()).select_from(AIUsage).where(AIUsage.status == "failed")
        )
        assert failed == 1  # the reservation for the skipped thread was released

        # A later run does not keep paying for the same failing thread.
        intelligence.analyze_pending(user_id)
        assert _states() == {"complete": 7, "analysis_failed": 1}
