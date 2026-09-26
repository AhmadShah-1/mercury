from flask import Blueprint, current_app, jsonify, render_template
from sqlalchemy import text

from mercury.extensions import db

bp = Blueprint("public", __name__)


@bp.get("/")
def index():
    return render_template("public/index.html")


@bp.get("/privacy")
def privacy():
    return render_template("public/privacy.html")


@bp.get("/terms")
def terms():
    return render_template("public/terms.html")


@bp.get("/help")
def help_page():
    return render_template("public/help.html")


@bp.get("/health/live")
def live():
    return jsonify(status="ok", release=current_app.config["RELEASE_ID"])


@bp.get("/health/ready")
def ready():
    try:
        db.session.execute(text("SELECT 1"))
        db.session.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception:
        current_app.logger.warning("readiness_failed", extra={"event_type": "readiness_failed"})
        return jsonify(status="unavailable"), 503
    return jsonify(status="ok")
