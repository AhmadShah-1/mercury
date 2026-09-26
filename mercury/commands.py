from __future__ import annotations

import click
from flask import current_app
from sqlalchemy import select

from mercury.accounts.models import GmailAccount, User
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
        analyze_pending(user.id)
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
