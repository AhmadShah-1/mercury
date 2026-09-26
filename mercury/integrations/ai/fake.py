from __future__ import annotations

import hashlib
import math

from mercury.integrations.types import AnalysisResult


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
