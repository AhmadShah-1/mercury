from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import click
from flask import current_app
from sqlalchemy import delete, select

from mercury.accounts.models import GmailAccount, OAuthAttempt, SecurityAuditEvent, User
from mercury.accounts.service import connect_fake_mailbox, get_or_create_demo_user
from mercury.buckets.service import seed_demo_buckets
from mercury.extensions import db
from mercury.inbox.service import create_run, index_account
from mercury.intelligence.service import analyze_pending


def register_commands(app) -> None:
    @app.cli.command("seed-demo")
    def seed_demo() -> None:
        if (
            current_app.config["APP_ENV"] == "production"
            or current_app.config["MAIL_MODE"] != "fake"
        ):
            raise click.ClickException("seed-demo is allowed only with the synthetic mailbox")
        user = get_or_create_demo_user()
        account = connect_fake_mailbox(user, ai_consent=True)
        run = create_run(user, account, kind="initial", limit=50)
        index_account(account, run, limit=run.requested_limit)
        analyze_pending(user.id, onboarding=True)
        seed_demo_buckets(account)
        click.echo(f"Synthetic workspace ready for {user.email}")

    @app.cli.command("promote-admin")
    @click.argument("email")
    def promote_admin(email: str) -> None:
        user = db.session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            raise click.ClickException("user not found")
        user.role = "admin"
        db.session.commit()
        click.echo("User promoted; no mailbox-reading permission was granted.")

    @app.cli.command("rotate-token-encryption")
    def rotate_token_encryption() -> None:
        cipher = current_app.extensions["mercury"]["token_cipher"]
        accounts = db.session.scalars(
            select(GmailAccount).where(GmailAccount.encrypted_token_bundle.is_not(None))
        ).all()
        for account in accounts:
            account.encrypted_token_bundle = cipher.rotate(account.encrypted_token_bundle)
        db.session.commit()
        click.echo(f"Rotated {len(accounts)} encrypted token bundles.")

    @app.cli.command("export-deletions")
    @click.option("--since", required=True, help="Inclusive ISO-8601 timestamp in UTC.")
    def export_deletions(since: str) -> None:
        try:
            cutoff = datetime.fromisoformat(since.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError as exc:
            raise click.ClickException("--since must be an ISO-8601 timestamp") from exc
        events = db.session.scalars(
            select(SecurityAuditEvent)
            .where(
                SecurityAuditEvent.event_type == "account_deleted",
                SecurityAuditEvent.created_at >= cutoff,
            )
            .order_by(SecurityAuditEvent.created_at, SecurityAuditEvent.id)
        ).all()
        for event in events:
            click.echo(
                json.dumps(
                    {
                        "event_id": str(event.id),
                        "user_id": str(event.resource_id),
                        "deleted_at": event.created_at.astimezone(UTC).isoformat(),
                    },
                    separators=(",", ":"),
                )
            )

    @app.cli.command("replay-deletions")
    @click.argument("events", type=click.File("r"))
    def replay_deletions(events) -> None:
        replayed = 0
        for line_number, line in enumerate(events, 1):
            if line_number > 100_000:
                raise click.ClickException("deletion replay file exceeds the safe record limit")
            try:
                payload = json.loads(line)
                user_id = uuid.UUID(payload["user_id"])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise click.ClickException(f"invalid deletion event at line {line_number}") from exc
            db.session.execute(delete(User).where(User.id == user_id))
            db.session.add(
                SecurityAuditEvent(
                    event_type="deletion_replayed",
                    resource_id=user_id,
                    outcome="success",
                )
            )
            replayed += 1
        db.session.commit()
        click.echo(f"Replayed {replayed} deletion events.")

    @app.cli.command("retention-cleanup")
    def retention_cleanup() -> None:
        now = datetime.now(UTC)
        oauth_result = db.session.execute(
            delete(OAuthAttempt).where(OAuthAttempt.expires_at < now - timedelta(days=1))
        )
        audit_result = db.session.execute(
            delete(SecurityAuditEvent).where(
                SecurityAuditEvent.created_at < now - timedelta(days=30)
            )
        )
        db.session.commit()
        click.echo(
            f"Removed {oauth_result.rowcount or 0} expired OAuth attempts and "
            f"{audit_result.rowcount or 0} expired audit events."
        )
