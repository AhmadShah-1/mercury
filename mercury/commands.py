from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import click
from flask import current_app
from sqlalchemy import delete, select, text

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

    @app.cli.command("queue-schema")
    def queue_schema() -> None:
        """Install the Procrastinate schema once; safe to run on every release."""
        installed = db.session.scalar(
            text("SELECT to_regclass('public.procrastinate_jobs') IS NOT NULL")
        )
        db.session.rollback()
        if installed:
            click.echo("Procrastinate schema already installed.")
            return
        queue_app = current_app.extensions["mercury"]["queue"]
        with queue_app.open():
            queue_app.schema_manager.apply_schema()
        click.echo("Procrastinate schema installed.")

    @app.cli.command("promote-admin")
    @click.argument("email")
    def promote_admin(email: str) -> None:
        user = db.session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            raise click.ClickException("user not found")
        user.role = "admin"
        db.session.commit()
        click.echo("User promoted; no mailbox-reading permission was granted.")

    @app.cli.command("bucket-scores")
    @click.argument("email")
    def bucket_scores(email: str) -> None:
        """Print similarity distributions for tuning the BUCKET_* thresholds (numbers only)."""
        import numpy as np

        from mercury.buckets.classification import (
            MIN_BUCKET_EXAMPLES,
            active_buckets_for,
            load_thread_vectors,
            members_by_bucket,
        )
        from mercury.buckets.clustering import fit_scores, neighbor_scores

        if current_app.config["APP_ENV"] == "production":
            raise click.ClickException("bucket-scores is a development tuning aid")
        user = db.session.scalar(select(User).where(User.email == email.lower()))
        account = user.gmail_account if user else None
        if account is None:
            raise click.ClickException("connected mailbox not found")
        config = current_app.config
        rows = load_thread_vectors(account)
        active = active_buckets_for(account)
        grouped = members_by_bucket(rows, active)

        def spread(values) -> str:
            if not values:
                return "-"
            return "/".join(f"{value:.2f}" for value in np.percentile(values, [10, 50, 90]))

        click.echo(
            f"match_min={config['BUCKET_MATCH_MIN']:.2f} margin={config['BUCKET_MATCH_MARGIN']:.2f}"
            f" keep_min={config['BUCKET_KEEP_MIN']:.2f}"
            f" split_max={config['BUCKET_SPLIT_MAX_SIMILARITY']:.2f}"
        )
        click.echo("bucket fit = mean similarity to nearest other members, p10/p50/p90")
        for bucket_id, members in sorted(grouped.items(), key=lambda item: -len(item[1])):
            fits = fit_scores([member.vector for member in members])
            misfits = sum(
                member.movable and score < config["BUCKET_KEEP_MIN"]
                for member, score in zip(members, fits, strict=True)
            )
            click.echo(
                f"  {active[bucket_id].name[:36]:36} n={len(members):4}"
                f" fit={spread(fits)} below_keep={misfits}"
            )
        examples = {
            bucket_id: [member.vector for member in members]
            for bucket_id, members in grouped.items()
            if len(members) >= MIN_BUCKET_EXAMPLES
        }
        unplaced = [row for row in rows if row.unplaced(active)]
        if not examples or not unplaced:
            click.echo(f"unplaced n={len(unplaced)} (nothing to compare)")
            return
        table = np.array(
            [neighbor_scores([row.vector for row in unplaced], v) for v in examples.values()]
        )
        ranked = np.sort(table, axis=0)[::-1]
        best = ranked[0]
        margin = best - ranked[1] if len(ranked) > 1 else best + 1.0
        placeable = int(
            ((best >= config["BUCKET_MATCH_MIN"]) & (margin >= config["BUCKET_MATCH_MARGIN"])).sum()
        )
        click.echo(
            f"unplaced n={len(unplaced)} best={spread(best.tolist())}"
            f" margin={spread(margin.tolist())} would_place={placeable}"
        )

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
