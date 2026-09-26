"""Bounded conversion of provider message content into safe, ephemeral text views."""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup

from mercury.integrations.types import ProviderMessage, ProviderThread


@dataclass(frozen=True)
class MessageView:
    id: str
    sender_name: str
    sender_address: str
    recipients: tuple[str, ...]
    sent_at: object
    text: str
    attachment_present: bool
    truncated: bool


@dataclass(frozen=True)
class ThreadView:
    id: str
    subject: str
    messages: tuple[MessageView, ...]


def _html_to_text(raw: str) -> str:
    soup = BeautifulSoup(raw, "html.parser")
    for element in soup(["script", "style", "form", "iframe", "svg", "object", "template"]):
        element.decompose()
    return "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())


def _message_text(message: ProviderMessage, max_bytes: int) -> tuple[str, bool]:
    text = _html_to_text(message.body) if message.mime_type == "text/html" else message.body
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def build_thread_view(thread: ProviderThread, *, max_bytes: int, max_messages: int) -> ThreadView:
    remaining = max_bytes
    views: list[MessageView] = []
    for message in reversed(thread.messages[-max_messages:]):
        if message.is_draft:
            continue
        text, truncated = _message_text(message, max(remaining, 0))
        remaining -= len(text.encode("utf-8"))
        views.append(
            MessageView(
                id=message.id,
                sender_name=message.sender_name,
                sender_address=message.sender_address,
                recipients=message.recipients,
                sent_at=message.sent_at,
                text=text,
                attachment_present=message.attachment_present,
                truncated=truncated or remaining <= 0,
            )
        )
        if remaining <= 0:
            break
    return ThreadView(thread.id, thread.subject, tuple(views))
