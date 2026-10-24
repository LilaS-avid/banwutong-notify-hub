from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class MessageIn(BaseModel):
    platform: Literal["manual", "qq", "wecom", "email", "file"] = "manual"
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


class TrashActivityOut(ActivityOut):
    deleted_at: str
    purge_after: str


class IngestOut(BaseModel):
    disposition: Literal["created", "updated", "duplicate"]
    activity: ActivityOut


class DocumentOut(BaseModel):
    id: int
    original_name: str
    media_type: str | None
    size_bytes: int
    sha256: str
    extract_status: Literal["processed", "stored_only", "failed"]
    extract_note: str | None
    analysis_method: str
    block_count: int
    activity_id: int | None
    created_at: str


class DocumentBlockOut(BaseModel):
    id: int
    locator: str
    block_type: str
    text: str
    ordinal: int


class FileUploadOut(BaseModel):
    disposition: Literal["created", "duplicate"]
    document: DocumentOut
    activity: ActivityOut | None
    activities: list[ActivityOut]


class ModelChoice(BaseModel):
    id: Literal["cloud", "rules"]
    label: str
    available: bool
    note: str


class ModelSettingsOut(BaseModel):
    provider: Literal["cloud", "rules"]
    choices: list[ModelChoice]


class ModelSettingsUpdate(BaseModel):
    provider: Literal["cloud", "rules"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)


class ChatResponse(BaseModel):
    reply: str
    provider: Literal["cloud"]


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

