from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

from mercury.extensions import db
from mercury.inbox.models import EmailThread
from mercury.intelligence.budget import finish_reservation, reserve_analysis
from mercury.intelligence.models import AIUsage, UsageBucket
from mercury.intelligence.service import analyze_thread


def test_budget_exhaustion_pauses_new_analysis(app, connected, monkeypatch):
    with app.app_context():
        thread = db.session.scalar(select(EmailThread))
        count_before = db.session.scalar(select(func.count()).select_from(AIUsage))
        monkeypatch.setitem(app.config, "AI_SUMMARY_INPUT_USD_PER_MILLION", Decimal("1000"))
        monkeypatch.setitem(app.config, "AI_SUMMARY_OUTPUT_USD_PER_MILLION", Decimal("1000"))
        monkeypatch.setitem(app.config, "AI_EMBEDDING_INPUT_USD_PER_MILLION", Decimal("1000"))
        monkeypatch.setitem(app.config, "AI_GLOBAL_MONTHLY_BUDGET_USD", Decimal("0.000001"))
        analyze_thread(thread)
        db.session.refresh(thread)
        assert thread.processing_state == "budget_paused"
        assert db.session.scalar(select(func.count()).select_from(AIUsage)) == count_before


def test_reservation_records_operator_rates_and_reconciles_actual_usage(
    app, connected, monkeypatch
):
    with app.app_context():
        thread = db.session.scalar(select(EmailThread))
        monkeypatch.setitem(app.config, "AI_SUMMARY_INPUT_USD_PER_MILLION", Decimal("2"))
        monkeypatch.setitem(app.config, "AI_SUMMARY_OUTPUT_USD_PER_MILLION", Decimal("8"))
        monkeypatch.setitem(app.config, "AI_EMBEDDING_INPUT_USD_PER_MILLION", Decimal("0.5"))
        usage = reserve_analysis(
            user_id=thread.user_id,
            thread_id=thread.id,
            estimated_input_tokens=100,
            estimated_output_tokens=20,
            estimated_embedding_tokens=80,
        )
        finish_reservation(
            usage.id,
            input_tokens=90,
            output_tokens=10,
            embedding_tokens=70,
        )
        db.session.refresh(usage)
        assert usage.status == "succeeded"
        assert usage.input_rate == Decimal("2.000000")
        assert usage.output_rate == Decimal("8.000000")
        assert usage.embedding_rate == Decimal("0.500000")
        assert usage.actual_usd > 0
        monthly = db.session.scalars(
            select(UsageBucket).where(UsageBucket.category == "ai-monthly")
        ).all()
        assert len(monthly) == 2
        assert all(item.reserved_usd == 0 for item in monthly)
        assert all(item.spent_usd > 0 for item in monthly)
