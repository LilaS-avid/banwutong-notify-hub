from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from zoneinfo import ZoneInfo

from app.config import STATIC_DIR, database_path, upload_directory
from app.documents import (
    ALLOWED_SUFFIXES,
    DocumentBlock,
    MAX_UPLOAD_BYTES,
    extract_document,
    safe_original_name,
)
from app.local_models import detect_local_model
from app.parser import parse_notification
from app.repository import ActivityRepository
from app.schemas import (
    ActivityEdit,
    ActivityOut,
    ChatRequest,
    ChatResponse,
    DocumentBlockOut,
    DocumentOut,
    FileUploadOut,
    HealthOut,
    IngestOut,
    MessageIn,
    ModelChoice,
    ModelSettingsOut,
    ModelSettingsUpdate,
    ReminderOut,
    StatusUpdate,
    TrashActivityOut,
)
from app.understanding import (
    chat_with_model,
    teleai_provider_available,
    understand_document,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def create_app(
    db_path: str | Path | None = None,
    upload_dir: str | Path | None = None,
    default_model_provider: str = "cloud",
) -> FastAPI:
    repository = ActivityRepository(Path(db_path) if db_path else database_path())
    selected_upload_dir = (
        Path(upload_dir) if upload_dir is not None else upload_directory()
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository.initialize()
        repository.purge_expired()
        selected_upload_dir.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(
        title="班务通 API",
        version="0.1.0",
        description="班级通知理解与报名提醒助手的最小闭环。",
        lifespan=lifespan,
    )
    app.state.repository = repository
    app.state.upload_dir = selected_upload_dir
    app.state.default_model_provider = default_model_provider

    def active_provider() -> str:
        requested = (
            repository.get_setting("model_provider")
            or default_model_provider
        )
        if requested not in {"cloud", "rules"}:
            requested = "cloud"
        if requested == "cloud" and not teleai_provider_available():
            return "rules"
        return requested

    def model_settings() -> ModelSettingsOut:
        cloud_model = os.getenv("BANWUTONG_LLM_MODEL", "").strip()
        return ModelSettingsOut(
            provider=active_provider(),
            choices=[
                ModelChoice(
                    id="cloud",
                    label="云端模型",
                    available=teleai_provider_available(),
                    note=(
                        f"已配置云端模型：{cloud_model}"
                        if cloud_model
                        else "云模型尚未配置"
                    ),
                ),
                ModelChoice(
                    id="rules",
                    label="本地规则",
                    available=True,
                    note="不联网、不调用外部模型",
                ),
            ],
        )

    def activity_context() -> str:
        activities = repository.list_activities()
        if not activities:
            return "当前没有已保存事项。"
        lines = []
        for activity in activities[:50]:
            deadline = activity.deadline or "未识别"
            materials = "、".join(activity.materials) or "未填写"
            lines.append(
                f"- {activity.title}；截止 {deadline}；状态 {activity.status}；"
                f"材料 {materials}"
            )
        return "\n".join(lines)

    @app.middleware("http")
    async def purge_expired_activities(request, call_next):
        if request.url.path.startswith("/api/"):
            repository.purge_expired()
        return await call_next(request)

    @app.get("/health", response_model=HealthOut)
    def health() -> HealthOut:
        return HealthOut(status="ok", service="banwutong")

    @app.post("/api/messages", response_model=IngestOut, status_code=201)
    async def ingest_message(payload: MessageIn) -> IngestOut:
        blocks = [
            DocumentBlock(
                locator="message-1",
                block_type="paragraph",
                text=payload.text,
            )
        ]
        understood = await asyncio.to_thread(
            understand_document,
            blocks,
            datetime.now(SHANGHAI),
            active_provider(),
        )
        parsed = [item.parsed for item in understood.activities]
        results = repository.ingest_many(payload, parsed)
        disposition, activity = results[0]
        return IngestOut(disposition=disposition, activity=activity)

    @app.get("/api/model-settings", response_model=ModelSettingsOut)
    def get_model_settings() -> ModelSettingsOut:
        return model_settings()

    @app.put("/api/model-settings", response_model=ModelSettingsOut)
    def update_model_settings(payload: ModelSettingsUpdate) -> ModelSettingsOut:
        choice = next(
            item for item in model_settings().choices if item.id == payload.provider
        )
        if not choice.available:
            raise HTTPException(
                status_code=409,
                detail=f"{choice.label} is not available",
            )
        repository.set_setting("model_provider", payload.provider)
        return model_settings()

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest) -> ChatResponse:
        provider = active_provider()
        if provider == "rules":
            raise HTTPException(
                status_code=409,
                detail="Chat requires the cloud model.",
            )
        try:
            reply, used_provider = await asyncio.to_thread(
                chat_with_model,
                [message.model_dump() for message in payload.messages],
                activity_context(),
                provider,
            )
        except Exception as error:
            raise HTTPException(
                status_code=502,
                detail="The selected model could not answer. Check its configuration and balance.",
            ) from error
        return ChatResponse(reply=reply, provider=used_provider)

    @app.post("/api/files", response_model=FileUploadOut, status_code=201)
    async def upload_file(file: UploadFile = File(...)) -> FileUploadOut:
        original_name = safe_original_name(file.filename)
        media_type = file.content_type
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type. Allowed: {allowed}",
            )

        content = await file.read()
        await file.close()
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded file is empty")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="The uploaded file exceeds the 20 MB limit",
            )

        digest = hashlib.sha256(content).hexdigest()
        existing = repository.get_document_by_hash(digest)
        if existing is not None:
            activities = repository.list_document_activities(existing.id)
            if not activities and existing.activity_id is not None:
                legacy_activity = repository.get_activity(existing.activity_id)
                activities = [legacy_activity] if legacy_activity else []
            return FileUploadOut(
                disposition="duplicate",
                document=existing,
                activity=activities[0] if activities else None,
                activities=activities,
            )

        stored_name = f"{uuid4().hex}{suffix}"
        target = selected_upload_dir / stored_name
        target.write_bytes(content)

        extraction = extract_document(target, suffix)
        activities: list[ActivityOut] = []
        active_model_provider = active_provider()
        understanding = await asyncio.to_thread(
            understand_document,
            extraction.blocks,
            datetime.now(SHANGHAI),
            active_model_provider,
        )
        message_id: int | None = None
        if (
            extraction.status == "processed"
            and extraction.text
            and understanding.activities
        ):
            payload = MessageIn(
                platform="file",
                external_id=f"file-{digest}",
                sender_id=original_name,
                text=extraction.text,
            )
            parsed = [item.parsed for item in understanding.activities]
            results = repository.ingest_many(payload, parsed)
            activities = [activity for _, activity in results]
            message_id = activities[0].source_message_id

        try:
            document = repository.create_document(
                original_name=original_name,
                stored_name=stored_name,
                media_type=media_type,
                size_bytes=len(content),
                sha256=digest,
                extract_status=extraction.status,
                extract_note="; ".join(
                    note
                    for note in (extraction.note, understanding.note)
                    if note
                ) or None,
                analysis_method=understanding.method,
                extracted_text=extraction.text,
                message_id=message_id,
                activity_id=activities[0].id if activities else None,
            )
            repository.save_document_structure(
                document.id,
                extraction.blocks,
                [activity.id for activity in activities],
                {
                    activity.id: understanding.activities[index].evidence
                    for index, activity in enumerate(activities)
                    if index < len(understanding.activities)
                },
            )
            document = repository.get_document(document.id) or document
        except Exception:
            target.unlink(missing_ok=True)
            raise

        return FileUploadOut(
            disposition="created",
            document=document,
            activity=activities[0] if activities else None,
            activities=activities,
        )

    @app.get("/api/files", response_model=list[DocumentOut])
    def list_files() -> list[DocumentOut]:
        return repository.list_documents()

    @app.get(
        "/api/files/{document_id}/blocks",
        response_model=list[DocumentBlockOut],
    )
    def list_file_blocks(document_id: int) -> list[DocumentBlockOut]:
        if repository.get_document(document_id) is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return repository.list_document_blocks(document_id)

    @app.get("/api/files/{document_id}/download")
    def download_file(document_id: int) -> FileResponse:
        document = repository.get_document(document_id)
        stored_name = repository.get_document_stored_name(document_id)
        if document is None or stored_name is None:
            raise HTTPException(status_code=404, detail="Document not found")
        path = selected_upload_dir / stored_name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Stored file not found")
        return FileResponse(
            path,
            media_type=document.media_type or "application/octet-stream",
            filename=document.original_name,
        )

    @app.get("/api/activities", response_model=list[ActivityOut])
    def list_activities(
        status: Literal["open", "completed", "ignored", "cancelled"] | None = None,
    ) -> list[ActivityOut]:
        return repository.list_activities(status)

    @app.patch("/api/activities/{activity_id}", response_model=ActivityOut)
    def update_activity(activity_id: int, payload: StatusUpdate) -> ActivityOut:
        activity = repository.set_status(activity_id, payload.status)
        if activity is None:
            raise HTTPException(status_code=404, detail="Activity not found")
        return activity

    @app.put("/api/activities/{activity_id}", response_model=ActivityOut)
    def edit_activity(activity_id: int, payload: ActivityEdit) -> ActivityOut:
        if payload.deadline and payload.deadline.tzinfo is None:
            payload.deadline = payload.deadline.replace(tzinfo=SHANGHAI)
        try:
            activity = repository.update_details(activity_id, payload)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if activity is None:
            raise HTTPException(status_code=404, detail="Activity not found")
        return activity

    @app.delete("/api/activities/{activity_id}", response_model=TrashActivityOut)
    def delete_activity(activity_id: int) -> TrashActivityOut:
        try:
            activity = repository.soft_delete(activity_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if activity is None:
            raise HTTPException(status_code=404, detail="Activity not found")
        return activity

    @app.post(
        "/api/activities/{activity_id}/restore",
        response_model=ActivityOut,
    )
    def restore_activity(activity_id: int) -> ActivityOut:
        activity = repository.restore_activity(activity_id)
        if activity is None:
            raise HTTPException(status_code=404, detail="Trashed activity not found")
        return activity

    @app.get("/api/trash", response_model=list[TrashActivityOut])
    def list_trash() -> list[TrashActivityOut]:
        return repository.list_trash()

    @app.delete("/api/trash/{activity_id}", status_code=204)
    def permanently_delete_activity(activity_id: int) -> Response:
        if not repository.purge_activity(activity_id):
            raise HTTPException(status_code=404, detail="Trashed activity not found")
        return Response(status_code=204)

    @app.get("/api/reminders", response_model=list[ReminderOut])
    def list_reminders(
        days: int = Query(default=7, ge=1, le=60),
    ) -> list[ReminderOut]:
        return [
            ReminderOut(activity=activity, due_state=due_state)
            for activity, due_state in repository.reminders(days)
        ]

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/chat", include_in_schema=False)
    def chat_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "chat.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()

