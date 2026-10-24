from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MessageIn(BaseModel):
    platform: Literal["manual", "qq", "wecom", "email"] = "manual"
    external_id: str = Field(min_length=1, max_length=200)
    group_id: str | None = Field(default=None, max_length=200)
    sender_id: str | None = Field(default=None, max_length=200)
    sent_at: datetime | None = None
    text: str = Field(min_length=1, max_length=50_000)

    @field_validator("external_id", "group_id", "sender_id", "text")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class ActivityOut(BaseModel):
    id: int
    title: str
    audience: str | None
    deadline: str | None
    location: str | None
    materials: list[str]
    registration_url: str | None
    contact: str | None
    status: str
    needs_review: bool
    source_message_id: int
    created_at: str
    updated_at: str


class IngestOut(BaseModel):
    disposition: Literal["created", "updated", "duplicate"]
    activity: ActivityOut


class StatusUpdate(BaseModel):
    status: Literal["open", "completed", "ignored", "cancelled"]


class ActivityEdit(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    audience: str | None = Field(default=None, max_length=500)
    deadline: datetime | None = None
    location: str | None = Field(default=None, max_length=500)
    materials: list[str] = Field(default_factory=list)
    registration_url: str | None = Field(default=None, max_length=2_000)
    contact: str | None = Field(default=None, max_length=500)

    @field_validator(
        "title",
        "audience",
        "location",
        "registration_url",
        "contact",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ReminderOut(BaseModel):
    activity: ActivityOut
    due_state: Literal["overdue", "today", "upcoming"]


class HealthOut(BaseModel):
    status: Literal["ok"]
    service: str

