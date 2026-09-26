from __future__ import annotations

import base64
import json

from flask import Blueprint, abort, current_app, jsonify, request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy import select

from mercury.accounts.models import GmailAccount
from mercury.extensions import csrf, db

bp = Blueprint("google_notifications", __name__)


@bp.post("/webhooks/google/pubsub")
@csrf.exempt
def pubsub_push():
    if current_app.config["SYNC_MODE"] != "push":
        abort(404)
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        abort(401)
    try:
        claims = id_token.verify_oauth2_token(
            authorization.removeprefix("Bearer "),
            google_requests.Request(),
            audience=current_app.config["PUBSUB_AUDIENCE"],
        )
    except ValueError:
        abort(401)
    if (
        claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}
        or claims.get("email") != current_app.config["PUBSUB_PUSH_SERVICE_ACCOUNT"]
        or claims.get("email_verified") is not True
    ):
        abort(401)
    envelope = request.get_json(silent=True)
    if (
        not isinstance(envelope, dict)
        or envelope.get("subscription") != current_app.config["PUBSUB_SUBSCRIPTION"]
    ):
        abort(400)
    encoded = envelope.get("message", {}).get("data", "")
    if not isinstance(encoded, str) or len(encoded) > 8192:
        abort(400)
    try:
        payload = json.loads(base64.b64decode(encoded, validate=True))
        email = payload["emailAddress"].lower()
        history_id = str(payload["historyId"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        abort(400)
    if not history_id.isdigit() or len(history_id) > 32:
        abort(400)
    account = db.session.scalar(select(GmailAccount).where(GmailAccount.mailbox_address == email))
    if account is None:
        return jsonify(status="ignored")
    account.pending_sync = True
    db.session.commit()
    try:
        from mercury.jobs.tasks import enqueue_sync

        enqueue_sync(current_app.extensions["mercury"]["queue"], account)
    except Exception:
        # Durable pending_sync is the source of truth; the periodic reconciler
        # closes the database-commit / queue-publication gap.
        current_app.logger.warning(
            "pubsub_enqueue_deferred", extra={"event_type": "pubsub_enqueue_deferred"}
        )
    return jsonify(status="accepted"), 202
