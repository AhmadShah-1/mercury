from __future__ import annotations

import base64
from datetime import UTC, datetime
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

from flask import current_app
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from mercury.accounts.models import GmailAccount
from mercury.extensions import db
from mercury.integrations.types import MailProfile, ProviderMessage, ProviderThread


class GmailProvider:
    def __init__(self, account: GmailAccount):
        self.account = account
        cipher = current_app.extensions["mercury"]["token_cipher"]
        bundle = cipher.decrypt(account.encrypted_token_bundle or "")
        self.credentials = Credentials(
            token=bundle.get("access_token") or bundle.get("token"),
            refresh_token=bundle.get("refresh_token"),
            token_uri=bundle.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=current_app.config["GOOGLE_CLIENT_ID"],
            client_secret=current_app.config["GOOGLE_CLIENT_SECRET"],
            scopes=account.granted_scopes,
        )
        self.service = build("gmail", "v1", credentials=self.credentials, cache_discovery=False)

    def _persist_refresh(self) -> None:
        if self.credentials.expired and self.credentials.refresh_token:
            self.credentials.refresh(Request())
            cipher = current_app.extensions["mercury"]["token_cipher"]
            previous = cipher.decrypt(self.account.encrypted_token_bundle or "")
            previous.update(
                access_token=self.credentials.token,
                refresh_token=self.credentials.refresh_token or previous.get("refresh_token"),
            )
            self.account.encrypted_token_bundle = cipher.encrypt(previous)
            db.session.commit()

    def profile(self) -> MailProfile:
        self._persist_refresh()
        result = self.service.users().getProfile(userId="me").execute()
        return MailProfile(
            self.account.provider_subject, result["emailAddress"], str(result["historyId"])
        )

    def list_threads(self, *, limit: int, after_epoch: int) -> list[ProviderThread]:
        self._persist_refresh()
        found: list[ProviderThread] = []
        token = None
        query = f"after:{after_epoch} -in:spam -in:trash -label:drafts"
        while len(found) < limit:
            page = (
                self.service.users()
                .threads()
                .list(
                    userId="me", q=query, maxResults=min(100, limit - len(found)), pageToken=token
                )
                .execute()
            )
            for item in page.get("threads", []):
                raw = (
                    self.service.users()
                    .threads()
                    .get(
                        userId="me",
                        id=item["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "From", "To", "Date", "Message-ID"],
                    )
                    .execute()
                )
                found.append(self._normalize_thread(raw, include_body=False))
            token = page.get("nextPageToken")
            if not token:
                break
        return found

    def get_thread(self, thread_id: str) -> ProviderThread:
        self._persist_refresh()
        raw = self.service.users().threads().get(userId="me", id=thread_id, format="full").execute()
        return self._normalize_thread(raw, include_body=True)

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
        return (
            self.service.users()
            .history()
            .list(userId="me", startHistoryId=start_history_id, pageToken=page_token)
            .execute()
        )

    def watch(self, topic_name: str) -> dict:
        return self.service.users().watch(userId="me", body={"topicName": topic_name}).execute()

    def stop_watch(self) -> None:
        self.service.users().stop(userId="me").execute()

    def list_labels(self) -> list[dict]:
        return self.service.users().labels().list(userId="me").execute().get("labels", [])

    def create_label(self, name: str) -> str:
        result = (
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
            .execute()
        )
        return result["id"]

    def apply_label(self, thread_id: str, *, add: list[str], remove: list[str]) -> None:
        self.service.users().threads().modify(
            userId="me", id=thread_id, body={"addLabelIds": add, "removeLabelIds": remove}
        ).execute()
