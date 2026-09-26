from __future__ import annotations

import uuid

import procrastinate
from flask import Flask
from sqlalchemy import select

from mercury.accounts.models import GmailAccount
from mercury.buckets.service import seed_demo_buckets
from mercury.extensions import db
from mercury.inbox.models import ProcessingRun
from mercury.inbox.service import index_account
from mercury.intelligence.service import analyze_pending

tasks = procrastinate.Blueprint()
_flask_app: Flask | None = None


def bind_flask_app(app: Flask) -> None:
    global _flask_app
    _flask_app = app


@tasks.task(name="discover_recent_threads", queue="mail", retry=5, pass_context=False)
def discover_recent_threads(*, account_id: str, connection_generation: int, run_id: str) -> None:
    if _flask_app is None:
        raise RuntimeError("worker Flask application is not bound")
    with _flask_app.app_context():
        account = db.session.get(GmailAccount, uuid.UUID(account_id))
        run = db.session.get(ProcessingRun, uuid.UUID(run_id))
        if account is None or run is None or account.connection_generation != connection_generation:
            return
        index_account(account, run, limit=run.requested_limit)
        if account.ai_consent:
            analyze_pending(account.user_id)
        if _flask_app.config["MAIL_MODE"] == "fake":
            seed_demo_buckets(account)


@tasks.task(name="reconcile_pending_work", queue="maintenance", retry=3)
def reconcile_pending_work() -> None:
    if _flask_app is None:
        raise RuntimeError("worker Flask application is not bound")
    with _flask_app.app_context():
        runs = db.session.scalars(
            select(ProcessingRun).where(ProcessingRun.status == "pending").limit(100)
        ).all()
        for run in runs:
            account = db.session.get(GmailAccount, run.gmail_account_id)
            if account and account.connection_state == "connected":
                current = _flask_app.extensions["mercury"]["queue"]
                enqueue_discovery(current, account, run)


def enqueue_discovery(queue_app, account: GmailAccount, run: ProcessingRun) -> int:
    with queue_app.open():
        return queue_app.configure_task("mercury:discover_recent_threads").defer(
            account_id=str(account.id),
            connection_generation=account.connection_generation,
            run_id=str(run.id),
        )
