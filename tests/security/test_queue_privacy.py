from sqlalchemy import Text, cast, select, text

from mercury.accounts.models import GmailAccount
from mercury.extensions import db
from mercury.inbox.models import ProcessingRun
from mercury.jobs.tasks import enqueue_discovery


def test_queue_payload_contains_ids_not_message_content(app, connected):
    with app.app_context():
        account = db.session.scalar(select(GmailAccount))
        run = db.session.scalar(select(ProcessingRun))
        enqueue_discovery(app.extensions["mercury"]["queue"], account, run)
        payloads = db.session.scalars(
            select(cast(text("args"), Text)).select_from(text("procrastinate_jobs"))
        ).all()
        assert payloads
        serialized = " ".join(payloads)
        assert str(account.id) in serialized
        assert "PERSISTENCE_SENTINEL_BODY_ONLY" not in serialized
        assert "Statement ready" not in serialized
