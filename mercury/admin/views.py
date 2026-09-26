from __future__ import annotations

from flask import Blueprint, abort, render_template
from flask_login import current_user, login_required
from sqlalchemy import func, select

from mercury.accounts.models import GmailAccount, User
from mercury.extensions import db
from mercury.inbox.models import ProcessingRun

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _require_admin() -> None:
    if not current_user.is_authenticated or current_user.role != "admin":
        abort(404)


@bp.get("/")
@login_required
def index():
    _require_admin()
    metrics = {
        "active_users": db.session.scalar(
            select(func.count()).select_from(User).where(User.active.is_(True))
        ),
        "connected_accounts": db.session.scalar(
            select(func.count())
            .select_from(GmailAccount)
            .where(GmailAccount.connection_state == "connected")
        ),
        "pending_runs": db.session.scalar(
            select(func.count())
            .select_from(ProcessingRun)
            .where(ProcessingRun.status.in_(["pending", "running"]))
        ),
    }
    recent_runs = db.session.scalars(
        select(ProcessingRun).order_by(ProcessingRun.created_at.desc()).limit(50)
    ).all()
    return render_template("admin/index.html", metrics=metrics, recent_runs=recent_runs)
