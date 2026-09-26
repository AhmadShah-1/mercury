from __future__ import annotations

from flask import abort
from flask_admin import Admin, AdminIndexView, expose
from flask_login import current_user
from sqlalchemy import func, select

from mercury.accounts.models import GmailAccount, User
from mercury.extensions import db
from mercury.inbox.models import ProcessingRun


class OperationsIndex(AdminIndexView):
    def is_accessible(self) -> bool:
        return bool(current_user.is_authenticated and current_user.role == "admin")

    def inaccessible_callback(self, name, **kwargs):
        abort(404)

    @expose("/")
    def index(self):
        if not self.is_accessible():
            abort(404)
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
        return self.render("admin/index.html", metrics=metrics, recent_runs=recent_runs)


def init_admin(app) -> None:
    admin = Admin(
        app,
        name="Mercury operations",
        index_view=OperationsIndex(name="Operations", url="/admin", endpoint="admin"),
    )
    app.extensions["mercury_admin"] = admin
