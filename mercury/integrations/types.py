from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ReauthorizationRequired(RuntimeError):
    """The stored Google grant can no longer be used; the user must reconnect Gmail."""


class InvalidProviderOutput(ValueError):
    """An AI reply for one item was unusable (refusal, empty, or off-schema); not retried.

    Callers skip that one item instead of failing the whole run, so a single odd reply cannot
    block every later thread behind it.
    """


class ProviderUnavailable(RuntimeError):
    """A transient provider failure (timeout, 429, 5xx) that may succeed on a bounded retry."""

    def __init__(self, code: str = "provider_unavailable", *, retry_after: int | None = None):
        super().__init__(code)
        self.retry_after = retry_after


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


@dataclass(frozen=True)
class ThreadDiscovery:
    """A bounded thread stream plus the provider's best available total."""

    estimated_count: int
    threads: Iterable[ProviderThread]


class MailProvider(Protocol):
    def profile(self) -> MailProfile: ...

    def list_threads(self, *, limit: int, after_epoch: int) -> ThreadDiscovery: ...

    def get_thread(self, thread_id: str) -> ProviderThread: ...

    def get_thread_metadata(self, thread_id: str) -> ProviderThread: ...


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


@dataclass(frozen=True)
class BucketSuggestion:
    name: str
    purpose: str
    input_tokens: int = 0
    output_tokens: int = 0


class AIProvider(Protocol):
    name: str

    def summarize(self, *, text: str, message_ids: tuple[str, ...]) -> AnalysisResult: ...

    def embed(self, text: str) -> tuple[list[float], int]: ...

    def suggest_bucket(self, *, descriptions: tuple[str, ...]) -> BucketSuggestion: ...
