"""Atomic AI budget reservations without retaining prompts or message content."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from flask import current_app
from sqlalchemy import select

from mercury.extensions import db
from mercury.intelligence.models import AIUsage, UsageBucket

MILLION = Decimal(1_000_000)
ZERO = Decimal(0)


class BudgetExceeded(RuntimeError):
    """Raised before a paid call when an account or global cap is exhausted."""


def _rate(name: str) -> Decimal:
    return current_app.config.get(name) or ZERO


def _cost(
    input_tokens: int,
    output_tokens: int,
    embedding_tokens: int,
    input_rate: Decimal,
    output_rate: Decimal,
    embedding_rate: Decimal,
) -> Decimal:
    return (
        Decimal(input_tokens) * input_rate
        + Decimal(output_tokens) * output_rate
        + Decimal(embedding_tokens) * embedding_rate
    ) / MILLION


def _locked_bucket(
    *, user_id: uuid.UUID | None, subject_key: str, category: str, window_start: date
) -> UsageBucket:
    bucket = db.session.scalar(
        select(UsageBucket)
        .where(
            UsageBucket.subject_key == subject_key,
            UsageBucket.category == category,
            UsageBucket.window_start == window_start,
        )
        .with_for_update()
    )
    if bucket is None:
        bucket = UsageBucket(
            user_id=user_id,
            subject_key=subject_key,
            category=category,
            window_start=window_start,
        )
        db.session.add(bucket)
        db.session.flush()
    return bucket


def reserve_analysis(
    *,
    user_id: uuid.UUID,
    thread_id: uuid.UUID,
    estimated_input_tokens: int,
    estimated_output_tokens: int,
    estimated_embedding_tokens: int,
    quota_category: str = "analysis-daily",
) -> AIUsage:
    input_rate = _rate("AI_SUMMARY_INPUT_USD_PER_MILLION")
    output_rate = _rate("AI_SUMMARY_OUTPUT_USD_PER_MILLION")
    embedding_rate = _rate("AI_EMBEDDING_INPUT_USD_PER_MILLION")
    reserved = _cost(
        estimated_input_tokens,
        estimated_output_tokens,
        estimated_embedding_tokens,
        input_rate,
        output_rate,
        embedding_rate,
    )
    today = datetime.now(UTC).date()
    month = today.replace(day=1)
    global_bucket = _locked_bucket(
        user_id=None, subject_key="global", category="ai-monthly", window_start=month
    )
    account_bucket = _locked_bucket(
        user_id=user_id,
        subject_key=f"user:{user_id}",
        category="ai-monthly",
        window_start=month,
    )
    daily_bucket = _locked_bucket(
        user_id=user_id,
        subject_key=f"user:{user_id}",
        category=quota_category,
        window_start=today,
    )
    global_limit = current_app.config["AI_GLOBAL_MONTHLY_BUDGET_USD"]
    account_limit = current_app.config["AI_ACCOUNT_MONTHLY_BUDGET_USD"]
    daily_limit = (
        current_app.config["AI_ONBOARDING_THREAD_LIMIT"]
        if quota_category == "analysis-onboarding"
        else current_app.config["AI_ACCOUNT_DAILY_THREAD_LIMIT"]
    )
    if (
        global_bucket.spent_usd + global_bucket.reserved_usd + reserved > global_limit
        or account_bucket.spent_usd + account_bucket.reserved_usd + reserved > account_limit
        or daily_bucket.operation_count >= daily_limit
    ):
        db.session.rollback()
        raise BudgetExceeded("ai_budget_paused")

    global_bucket.reserved_usd += reserved
    global_bucket.operation_count += 1
    account_bucket.reserved_usd += reserved
    account_bucket.operation_count += 1
    daily_bucket.operation_count += 1
    usage = AIUsage(
        user_id=user_id,
        thread_id=thread_id,
        category="thread-analysis",
        model=current_app.config["SUMMARY_MODEL"],
        input_tokens=estimated_input_tokens,
        output_tokens=estimated_output_tokens,
        embedding_tokens=estimated_embedding_tokens,
        input_rate=input_rate,
        output_rate=output_rate,
        embedding_rate=embedding_rate,
        reserved_usd=reserved,
        status="reserved",
    )
    db.session.add(usage)
    db.session.commit()
    return usage


def reserve_bucket_naming(
    *, user_id: uuid.UUID, estimated_input_tokens: int, estimated_output_tokens: int
) -> AIUsage:
    """Reserve a bounded naming call against monetary caps, not the thread-analysis quota."""
    input_rate = _rate("AI_SUMMARY_INPUT_USD_PER_MILLION")
    output_rate = _rate("AI_SUMMARY_OUTPUT_USD_PER_MILLION")
    reserved = _cost(
        estimated_input_tokens,
        estimated_output_tokens,
        0,
        input_rate,
        output_rate,
        ZERO,
    )
    month = datetime.now(UTC).date().replace(day=1)
    global_bucket = _locked_bucket(
        user_id=None, subject_key="global", category="ai-monthly", window_start=month
    )
    account_bucket = _locked_bucket(
        user_id=user_id,
        subject_key=f"user:{user_id}",
        category="ai-monthly",
        window_start=month,
    )
    if (
        global_bucket.spent_usd + global_bucket.reserved_usd + reserved
        > current_app.config["AI_GLOBAL_MONTHLY_BUDGET_USD"]
        or account_bucket.spent_usd + account_bucket.reserved_usd + reserved
        > current_app.config["AI_ACCOUNT_MONTHLY_BUDGET_USD"]
    ):
        db.session.rollback()
        raise BudgetExceeded("ai_budget_paused")

    global_bucket.reserved_usd += reserved
    global_bucket.operation_count += 1
    account_bucket.reserved_usd += reserved
    account_bucket.operation_count += 1
    usage = AIUsage(
        user_id=user_id,
        thread_id=None,
        category="bucket-naming",
        model=current_app.config["SUMMARY_MODEL"],
        input_tokens=estimated_input_tokens,
        output_tokens=estimated_output_tokens,
        embedding_tokens=0,
        input_rate=input_rate,
        output_rate=output_rate,
        embedding_rate=ZERO,
        reserved_usd=reserved,
        status="reserved",
    )
    db.session.add(usage)
    db.session.commit()
    return usage


def finish_reservation(
    usage_id: uuid.UUID,
    *,
    input_tokens: int,
    output_tokens: int,
    embedding_tokens: int,
    status: str = "succeeded",
) -> None:
    usage = db.session.get(AIUsage, usage_id, with_for_update=True)
    if usage is None or usage.status != "reserved":
        return
    month = usage.created_at.astimezone(UTC).date().replace(day=1)
    buckets = (
        _locked_bucket(
            user_id=None, subject_key="global", category="ai-monthly", window_start=month
        ),
        _locked_bucket(
            user_id=usage.user_id,
            subject_key=f"user:{usage.user_id}",
            category="ai-monthly",
            window_start=month,
        ),
    )
    actual = _cost(
        input_tokens,
        output_tokens,
        embedding_tokens,
        usage.input_rate,
        usage.output_rate,
        usage.embedding_rate,
    )
    for bucket in buckets:
        bucket.reserved_usd = max(ZERO, bucket.reserved_usd - usage.reserved_usd)
        if status == "succeeded":
            bucket.spent_usd += actual
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.embedding_tokens = embedding_tokens
    usage.actual_usd = actual if status == "succeeded" else ZERO
    usage.status = status
    db.session.commit()


def cancel_reservation(usage_id: uuid.UUID, *, status: str = "failed") -> None:
    finish_reservation(usage_id, input_tokens=0, output_tokens=0, embedding_tokens=0, status=status)
