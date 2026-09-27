from __future__ import annotations

from flask import Flask

from mercury.security.headers import init_security_headers


def _csp_for(auth_mode: str) -> str:
    app = Flask(__name__)
    app.config.update(AUTH_MODE=auth_mode, APP_ENV="development")
    init_security_headers(app)

    @app.get("/")
    def index():
        return "ok"

    return app.test_client().get("/").headers["Content-Security-Policy"]


def test_google_oauth_authorization_origin_is_an_allowed_form_action():
    csp = _csp_for("google")

    assert "form-action 'self' https://accounts.google.com;" in csp


def test_synthetic_auth_keeps_form_actions_same_origin_only():
    csp = _csp_for("dev")

    assert "form-action 'self';" in csp
    assert "https://accounts.google.com" not in csp
