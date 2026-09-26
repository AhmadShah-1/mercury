from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class MailProfile:
    subject: str
    email: str
    history_id: str


@dataclass(frozen=True)
class ProviderMessage:
    id: str
    internet_message_id: str | None
    sender_name: str
    sender_address: str
    recipients: tuple[str, ...]
    sent_at: datetime
    labels: tuple[str, ...]
    mime_type: str
    body: str
    attachment_present: bool = False
    is_draft: bool = False


@dataclass(frozen=True)
class ProviderThread:
    id: str
    subject: str
    messages: tuple[ProviderMessage, ...]
    unread: bool = False
    snippet: str = ""


class MailProvider(Protocol):
    def profile(self) -> MailProfile: ...

    def list_threads(self, *, limit: int, after_epoch: int) -> list[ProviderThread]: ...

    def get_thread(self, thread_id: str) -> ProviderThread: ...


@dataclass(frozen=True)
class AnalysisResult:
    summary: str
    action_required: bool
    action_type: str
    action_text: str | None
    due_date: str | None
    source_message_id: str | None
    uncertain: bool
    input_tokens: int = 0
    output_tokens: int = 0


class AIProvider(Protocol):
    name: str

    def summarize(self, *, text: str, message_ids: tuple[str, ...]) -> AnalysisResult: ...

    def embed(self, text: str) -> tuple[list[float], int]: ...
