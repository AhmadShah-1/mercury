from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SummaryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    summary: str = Field(min_length=1, max_length=700)
    action_required: bool
    action_type: Literal["none", "reply", "review", "pay", "schedule", "read", "unknown"]
    action_text: str | None = Field(default=None, max_length=500)
    due_date: date | None = None
    source_message_id: str | None = Field(default=None, max_length=128)
    uncertain: bool


class BucketSuggestionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1, max_length=240)

    @field_validator("name")
    @classmethod
    def short_name(cls, value: str) -> str:
        if not 2 <= len(value.split()) <= 4:
            raise ValueError("bucket names must contain two to four words")
        return value
