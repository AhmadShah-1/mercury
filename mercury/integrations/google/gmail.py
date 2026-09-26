from __future__ import annotations

import base64
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

import httplib2
from flask import current_app
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select

from mercury.accounts.models import GmailAccount
from mercury.extensions import db
from mercury.integrations.types import (
    MailProfile,
    ProviderMessage,
    ProviderThread,
    ProviderUnavailable,
    ReauthorizationRequired,
)


def _retry_after(error: HttpError) -> int | None:
    value = getattr(error.resp, "get", lambda _name: None)("retry-after")
    try:
        return max(0, min(int(value), 3600)) if value is not None else None
    except (TypeError, ValueError):
        return None


class GmailProvider:
    def __init__(self, account: GmailAccount):
        self.account = account
        cipher = current_app.extensions["mercury"]["token_cipher"]
        bundle = cipher.decrypt(account.encrypted_token_bundle or "")
        self.credentials = self._credentials_from_bundle(bundle, account.granted_scopes)
        self.service = self._build_service(self.credentials)

    @staticmethod
    def _build_service(credentials: Credentials):
        # A finite socket timeout bounds every Gmail call made by web or worker code.
        http = httplib2.Http(timeout=current_app.config["PROVIDER_TIMEOUT_SECONDS"])
        return build(
            "gmail", "v1", http=AuthorizedHttp(credentials, http=http), cache_discovery=False
        )

    @staticmethod
    def _execute(request, *, translate_not_found: bool = True):
        """Execute one Gmail request, translating provider failures into safe error types."""
        try:
            return request.execute(num_retries=1)
        except HttpError as error:
            status = getattr(error.resp, "status", None)
            if status == 404 and translate_not_found:
                raise LookupError("provider_resource_not_found") from None
            if status == 401:
                raise ReauthorizationRequired("connection_needs_reauthorization") from None
            if status == 429:
                raise ProviderUnavailable(
                    "provider_rate_limited", retry_after=_retry_after(error)
                ) from None
            if status is not None and int(status) >= 500:
                raise ProviderUnavailable(retry_after=_retry_after(error)) from None
            raise
        except (TimeoutError, OSError, httplib2.HttpLib2Error, TransportError):
            raise ProviderUnavailable("provider_timeout") from None

    @staticmethod
    def _credentials_from_bundle(bundle: dict, granted_scopes: list[str]) -> Credentials:
        expires_at = bundle.get("expires_at")
        expiry = (
            datetime.fromtimestamp(float(expires_at), UTC).replace(tzinfo=None)
            if expires_at
            else None
        )
        return Credentials(
            token=bundle.get("access_token") or bundle.get("token"),
            refresh_token=bundle.get("refresh_token"),
            token_uri=bundle.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=current_app.config["GOOGLE_CLIENT_ID"],
            client_secret=current_app.config["GOOGLE_CLIENT_SECRET"],
            scopes=granted_scopes,
            expiry=expiry,
        )

    def _persist_refresh(self) -> None:
        """Refresh an unusable access token under a row lock so concurrent refreshes serialize.

        Another process may already have refreshed and stored a newer token while this one
        waited for the lock; that stored token is reused instead of refreshing again.
        """
        if self.credentials.valid:
            return
        if not self.credentials.refresh_token:
            raise ReauthorizationRequired("connection_needs_reauthorization")
        cipher = current_app.extensions["mercury"]["token_cipher"]
        locked = db.session.scalar(
            select(GmailAccount).where(GmailAccount.id == self.account.id).with_for_update()
        )
        if locked is None or locked.connection_state != "connected":
            db.session.rollback()
            raise ReauthorizationRequired("connection_needs_reauthorization")
        previous = cipher.decrypt(locked.encrypted_token_bundle or "")
        credentials = self._credentials_from_bundle(previous, locked.granted_scopes)
        if not credentials.valid:
            if not credentials.refresh_token:
                db.session.rollback()
                raise ReauthorizationRequired("connection_needs_reauthorization")
            try:
                credentials.refresh(Request(timeout=current_app.config["PROVIDER_TIMEOUT_SECONDS"]))
            except RefreshError as error:
                if error.retryable:
                    db.session.rollback()
                    raise ProviderUnavailable() from None
                # invalid_grant and other permanent refresh failures require reconnection.
                locked.connection_state = "reconnect_required"
                db.session.commit()
                raise ReauthorizationRequired("connection_needs_reauthorization") from None
            except TransportError:
                db.session.rollback()
                raise ProviderUnavailable("provider_timeout") from None
            previous.update(
                access_token=credentials.token,
                refresh_token=credentials.refresh_token or previous.get("refresh_token"),
                expires_at=(
                    int(credentials.expiry.replace(tzinfo=UTC).timestamp())
                    if credentials.expiry
                    else previous.get("expires_at")
                ),
            )
            locked.encrypted_token_bundle = cipher.encrypt(previous)
        self.account = locked
        self.credentials = credentials
        self.service = self._build_service(self.credentials)
        db.session.commit()

    def profile(self) -> MailProfile:
        self._persist_refresh()
        result = self._execute(self.service.users().getProfile(userId="me"))
        return MailProfile(
            self.account.provider_subject, result["emailAddress"], str(result["historyId"])
        )

    def list_threads(self, *, limit: int, after_epoch: int) -> list[ProviderThread]:
        self._persist_refresh()
        found: list[ProviderThread] = []
        token = None
        query = f"after:{after_epoch} -in:spam -in:trash -label:drafts"
        while len(found) < limit:
            page = self._execute(
                self.service.users()
                .threads()
                .list(
                    userId="me", q=query, maxResults=min(100, limit - len(found)), pageToken=token
                )
            )
            for item in page.get("threads", []):
                try:
                    raw = self._execute(
                        self.service.users()
                        .threads()
                        .get(
                            userId="me",
                            id=item["id"],
                            format="metadata",
                            metadataHeaders=["Subject", "From", "To", "Date", "Message-ID"],
                        )
                    )
                except LookupError:
                    continue  # Deleted between list and get; the next sync reconciles it.
                found.append(self._normalize_thread(raw, include_body=False))
            token = page.get("nextPageToken")
            if not token:
                break
        return found

    def get_thread(self, thread_id: str) -> ProviderThread:
        self._persist_refresh()
        raw = self._execute(
            self.service.users().threads().get(userId="me", id=thread_id, format="full")
        )
        return self._normalize_thread(raw, include_body=True)

    def get_thread_metadata(self, thread_id: str) -> ProviderThread:
        self._persist_refresh()
        raw = self._execute(
            self.service.users()
            .threads()
            .get(
                userId="me",
                id=thread_id,
                format="metadata",
                metadataHeaders=["Subject", "From", "To", "Date", "Message-ID"],
            )
        )
        return self._normalize_thread(raw, include_body=False)

    @staticmethod
    def _header(payload: dict, name: str) -> str:
        for header in payload.get("headers", []):
            if header.get("name", "").lower() == name.lower():
                try:
                    return str(make_header(decode_header(header.get("value", ""))))
                except (UnicodeError, LookupError):
                    return header.get("value", "")
        return ""

    @classmethod
    def _body(cls, payload: dict, depth: int = 0) -> tuple[str, str, bool]:
        if depth > current_app.config["MAX_MIME_DEPTH"]:
            return "", "text/plain", False
        attachment = bool(payload.get("filename") or payload.get("body", {}).get("attachmentId"))
        if attachment:
            return "", "text/plain", True
        mime = payload.get("mimeType", "")
        data = payload.get("body", {}).get("data")
        if mime in {"text/plain", "text/html"} and data:
            try:
                return (
                    base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                        "utf-8", "replace"
                    ),
                    mime,
                    False,
                )
            except (ValueError, UnicodeError):
                return "", "text/plain", False
        plain, html = None, None
        any_attachment = False
        for part in payload.get("parts", []):
            body, part_mime, part_attachment = cls._body(part, depth + 1)
            any_attachment |= part_attachment
            if part_mime == "text/plain" and body and plain is None:
                plain = body
            elif part_mime == "text/html" and body and html is None:
                html = body
        return (
            (plain, "text/plain", any_attachment)
            if plain is not None
            else (html or "", "text/html", any_attachment)
        )

    @classmethod
    def _normalize_thread(cls, raw: dict, *, include_body: bool) -> ProviderThread:
        messages: list[ProviderMessage] = []
        subject = "(no subject)"
        for item in raw.get("messages", []):
            payload = item.get("payload", {})
            subject = cls._header(payload, "Subject") or subject
            from_values = getaddresses([cls._header(payload, "From")])
            sender_name, sender_address = from_values[0] if from_values else ("", "unknown@invalid")
            recipients = tuple(address for _, address in getaddresses([cls._header(payload, "To")]))
            try:
                sent_at = parsedate_to_datetime(cls._header(payload, "Date"))
            except (TypeError, ValueError, OverflowError):
                sent_at = datetime.fromtimestamp(int(item.get("internalDate", "0")) / 1000, UTC)
            body, mime, attachment = (
                cls._body(payload) if include_body else ("", "text/plain", False)
            )
            messages.append(
                ProviderMessage(
                    id=item["id"],
                    internet_message_id=cls._header(payload, "Message-ID") or None,
                    sender_name=sender_name,
                    sender_address=sender_address,
                    recipients=recipients,
                    sent_at=sent_at,
                    labels=tuple(item.get("labelIds", [])),
                    mime_type=mime,
                    body=body,
                    attachment_present=attachment,
                    is_draft="DRAFT" in item.get("labelIds", []),
                )
            )
        return ProviderThread(
            id=raw["id"],
            subject=subject,
            messages=tuple(messages),
            unread=any("UNREAD" in message.labels for message in messages),
            snippet=raw.get("snippet", ""),
        )

    def list_history(self, start_history_id: str, page_token: str | None = None) -> dict:
        self._persist_refresh()
        # An expired checkpoint returns HTTP 404; sync.py handles that HttpError explicitly.
        return self._execute(
            self.service.users()
            .history()
            .list(userId="me", startHistoryId=start_history_id, pageToken=page_token),
            translate_not_found=False,
        )

    def watch(self, topic_name: str) -> dict:
        self._persist_refresh()
        return self._execute(
            self.service.users().watch(userId="me", body={"topicName": topic_name})
        )

    def stop_watch(self) -> None:
        self._persist_refresh()
        self._execute(self.service.users().stop(userId="me"))

    def list_labels(self) -> list[dict]:
        self._persist_refresh()
        return self._execute(self.service.users().labels().list(userId="me")).get("labels", [])

    def create_label(self, name: str) -> str:
        self._persist_refresh()
        result = self._execute(
            self.service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
        )
        return result["id"]

    def apply_label(self, thread_id: str, *, add: list[str], remove: list[str]) -> None:
        self._persist_refresh()
        self._execute(
            self.service.users()
            .threads()
            .modify(userId="me", id=thread_id, body={"addLabelIds": add, "removeLabelIds": remove})
        )
