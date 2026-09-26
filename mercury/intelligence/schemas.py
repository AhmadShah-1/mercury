from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str = Field(min_length=1, max_length=700)
    action_required: bool
    action_type: Literal["none", "reply", "review", "pay", "schedule", "read", "unknown"]
    action_text: str | None = Field(default=None, max_length=500)
    due_date: date | None = None
    source_message_id: str | None = Field(default=None, max_length=128)
    uncertain: bool
