from __future__ import annotations

import base64
from types import SimpleNamespace

from mercury.integrations.ai.openai import OpenAIProvider
from mercury.integrations.google.gmail import GmailProvider
from mercury.intelligence.schemas import BucketSuggestionOutput, SummaryOutput


class _Responses:
    def __init__(self):
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if kwargs["text_format"] is BucketSuggestionOutput:
            parsed = BucketSuggestionOutput(
                name="Project Planning",
                purpose="Planning discussions and related project decisions.",
            )
        else:
            parsed = SummaryOutput(
                summary="A bounded result.",
                action_required=False,
                action_type="none",
                action_text=None,
                due_date=None,
                source_message_id="message-1",
                uncertain=False,
            )
        return SimpleNamespace(
            output_parsed=parsed,
            usage=SimpleNamespace(input_tokens=12, output_tokens=4),
        )


class _Embeddings:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.0] * 512)],
            usage=SimpleNamespace(total_tokens=9),
        )


def test_openai_adapter_uses_structured_responses_without_storage_or_tools():
    provider = OpenAIProvider(
        api_key="fixture-key",
        summary_model="gpt-4.1-mini-2025-04-14",
        embedding_model="text-embedding-3-small",
        dimensions=512,
        timeout=5,
    )
    responses = _Responses()
    embeddings = _Embeddings()
    provider.client = SimpleNamespace(responses=responses, embeddings=embeddings)
    result = provider.summarize(text="Invented message", message_ids=("message-1",))
    vector, tokens = provider.embed("Invented message")

    assert result.source_message_id == "message-1"
    assert responses.kwargs["store"] is False
    assert responses.kwargs["text_format"] is SummaryOutput
    assert "tools" not in responses.kwargs
    assert embeddings.kwargs["dimensions"] == 512
    assert embeddings.kwargs["model"] == "text-embedding-3-small"
    assert len(vector) == 512 and tokens == 9


def test_openai_bucket_naming_is_bounded_structured_and_not_stored():
    provider = OpenAIProvider(
        api_key="fixture-key",
        summary_model="gpt-4.1-mini-2025-04-14",
        embedding_model="text-embedding-3-small",
        dimensions=512,
        timeout=5,
    )
    responses = _Responses()
    provider.client = SimpleNamespace(responses=responses)

    suggestion = provider.suggest_bucket(
        descriptions=tuple(f"description {index}" for index in range(8))
    )

    assert suggestion.name == "Project Planning"
    assert responses.kwargs["store"] is False
    assert responses.kwargs["text_format"] is BucketSuggestionOutput
    assert "description 4" in responses.kwargs["input"]
    assert "description 5" not in responses.kwargs["input"]
    assert "tools" not in responses.kwargs


def test_gmail_adapter_exposes_no_forbidden_operations():
    forbidden = {"send", "draft", "delete", "trash", "archive", "get_attachment"}
    assert forbidden.isdisjoint(dir(GmailProvider))


def test_gmail_mime_parser_prefers_plain_text_and_skips_attachment_parts(app):
    encoded_plain = base64.urlsafe_b64encode(b"safe plain text").decode().rstrip("=")
    encoded_html = (
        base64.urlsafe_b64encode(b"<img src='https://tracker.invalid'>").decode().rstrip("=")
    )
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/html", "body": {"data": encoded_html}},
            {"mimeType": "text/plain", "body": {"data": encoded_plain}},
            {
                "mimeType": "application/pdf",
                "filename": "statement.pdf",
                "body": {"attachmentId": "attachment-id"},
            },
        ],
    }
    with app.app_context():
        body, mime, attachment = GmailProvider._body(payload)
    assert body == "safe plain text"
    assert mime == "text/plain"
    assert attachment is True
