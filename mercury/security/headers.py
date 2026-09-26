"""Request correlation and browser security headers."""

from __future__ import annotations

import uuid

from flask import Flask, g, request


def init_security_headers(app: Flask) -> None:
    @app.before_request
    def assign_request_id() -> None:
        g.request_id = uuid.uuid4().hex

    @app.after_request
    def secure_response(response):
        response.headers["X-Request-ID"] = g.get("request_id", uuid.uuid4().hex)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; img-src 'self' data:; object-src 'none'; "
            "script-src 'self'; style-src 'self'; connect-src 'self'"
        )
        if request.path.startswith(("/app", "/settings", "/admin")):
            response.headers["Cache-Control"] = "no-store, private"
        if app.config["APP_ENV"] == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
