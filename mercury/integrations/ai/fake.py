from __future__ import annotations

import hashlib
import math

from mercury.integrations.types import AnalysisResult, BucketSuggestion


class FakeAIProvider:
    name = "fake"

    def summarize(self, *, text: str, message_ids: tuple[str, ...]) -> AnalysisResult:
        lower = text.lower()
        if "review" in lower and "forecast" in lower:
            summary = "The sender asks you to review a revised launch forecast. [Synthetic]"
            action_type, action_text = "review", "Review the revised forecast and respond."
        elif "confirm whether" in lower or "could you" in lower:
            summary = "The sender asks for confirmation about a workshop time. [Synthetic]"
            action_type, action_text = "reply", "Confirm the workshop start time."
        elif "statement" in lower:
            summary = "A fictional monthly statement is available. [Synthetic]"
            action_type, action_text = "read", "Review the statement if needed."
        else:
            summary = "This message is informational or lacks a clear request. [Synthetic]"
            action_type, action_text = "none", None
        return AnalysisResult(
            summary=summary,
            action_required=action_type != "none",
            action_type=action_type,
            action_text=action_text,
            due_date=None,
            source_message_id=message_ids[-1] if message_ids else None,
            uncertain="following up" in lower,
            input_tokens=max(1, len(text) // 4),
            output_tokens=max(1, len(summary) // 4),
        )

    def embed(self, text: str) -> tuple[list[float], int]:
        values: list[float] = []
        counter = 0
        while len(values) < 512:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            values.extend((byte - 127.5) / 127.5 for byte in digest)
            counter += 1
        vector = values[:512]
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector], max(1, len(text) // 4)

    def suggest_bucket(self, *, descriptions: tuple[str, ...]) -> BucketSuggestion:
        text = " ".join(descriptions).lower()
        if any(word in text for word in ("invoice", "statement", "payment", "bank")):
            name = "Financial Notices"
            purpose = "Statements, invoices, and other fictional financial notices."
        elif any(word in text for word in ("order", "purchase", "shipped", "delivery")):
            name = "Orders and Deliveries"
            purpose = "Purchase confirmations and fictional delivery updates."
        elif any(word in text for word in ("project", "forecast", "review", "workshop")):
            name = "Projects and Reviews"
            purpose = "Project discussions, reviews, and follow-up requests."
        else:
            name = "Recurring Reading"
            purpose = "Related informational conversations suggested from synthetic data."
        return BucketSuggestion(
            name=name,
            purpose=purpose,
            input_tokens=max(1, sum(len(item) for item in descriptions) // 4),
            output_tokens=max(1, (len(name) + len(purpose)) // 4),
        )
