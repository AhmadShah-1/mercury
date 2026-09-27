from __future__ import annotations

import logging

from flask import Flask, abort, render_template, session
from flask_login import current_user
from werkzeug.exceptions import SecurityError
from werkzeug.middleware.proxy_fix import ProxyFix

from mercury.config import load_config
from mercury.extensions import csrf, db, login_manager, migrate, oauth
from mercury.security.crypto import TokenCipher
from mercury.security.headers import init_security_headers


def create_app(config_overrides=None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(load_config(config_overrides))
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if app.config["PROXY_HOPS"]:
        hops = app.config["PROXY_HOPS"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    oauth.init_app(app)
    login_manager.login_view = "accounts.dev_login" if app.config["AUTH_MODE"] == "dev" else None

    # Import all mapped classes before migrations and relationship configuration.
    from mercury.accounts import models as accounts_models
    from mercury.buckets import models as bucket_models
    from mercury.inbox import models as inbox_models
    from mercury.integrations.ai.fake import FakeAIProvider
    from mercury.integrations.ai.openai import OpenAIProvider
    from mercury.integrations.fake_gmail import FakeGmailProvider
    from mercury.integrations.google.gmail import GmailProvider
    from mercury.integrations.google.oauth import register_google_client
    from mercury.intelligence import models as intelligence_models
    from mercury.jobs.queue import create_queue_app

    del accounts_models, bucket_models, inbox_models, intelligence_models

    token_cipher = TokenCipher(app.config["TOKEN_ENCRYPTION_KEYS"])
    fake_mail = FakeGmailProvider()

    def mail_provider(account):
        return fake_mail if app.config["MAIL_MODE"] == "fake" else GmailProvider(account)

    ai = (
        FakeAIProvider()
        if app.config["AI_PROVIDER"] == "fake"
        else OpenAIProvider(
            api_key=app.config["OPENAI_API_KEY"],
            base_url=app.config["OPENAI_BASE_URL"],
            summary_model=app.config["SUMMARY_MODEL"],
            embedding_model=app.config["EMBEDDING_MODEL"],
            dimensions=app.config["EMBEDDING_DIMENSIONS"],
            timeout=app.config["PROVIDER_TIMEOUT_SECONDS"],
        )
    )
    app.extensions["mercury"] = {
        "token_cipher": token_cipher,
        "mail_provider": mail_provider,
        "ai_provider": ai,
        "queue": create_queue_app(app.config["SQLALCHEMY_DATABASE_URI"]),
    }
    register_google_client(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        try:
            return db.session.get(User, uuid.UUID(user_id))
        except (ValueError, TypeError):
            return None

    import uuid

    from mercury.accounts.models import User

    @app.before_request
    def enforce_session_generation():
        if current_user.is_authenticated and (
            not current_user.active
            or session.get("session_generation") != str(current_user.session_generation)
        ):
            session.clear()
            abort(401)

    from mercury.accounts.routes import bp as accounts_bp
    from mercury.admin.views import init_admin
    from mercury.buckets.routes import bp as buckets_bp
    from mercury.inbox.routes import bp as inbox_bp
    from mercury.integrations.google.notifications import bp as notifications_bp
    from mercury.public.routes import bp as public_bp

    for blueprint in (public_bp, accounts_bp, inbox_bp, buckets_bp, notifications_bp):
        app.register_blueprint(blueprint)
    init_admin(app)

    from mercury.commands import register_commands

    register_commands(app)
    init_security_headers(app)

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    def safe_client_error(error):
        if isinstance(error, SecurityError):
            # Routing has no trusted URL adapter for a rejected Host header, so this
            # response intentionally avoids template URL generation.
            return "<!doctype html><title>Invalid request</title><h1>Invalid request</h1>", 400
        return render_template("errors/error.html", code=error.code), error.code

    @app.errorhandler(500)
    def safe_server_error(error):
        app.logger.error("request_failed", extra={"event_type": "request_failed"})
        return render_template("errors/error.html", code=500), 500

    @app.errorhandler(503)
    def safe_unavailable(error):
        return render_template("errors/error.html", code=503), 503

    return app


__all__ = ["create_app"]
