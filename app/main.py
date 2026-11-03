from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import hmac
import logging
import os
from pathlib import Path
import secrets
import time
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from zoneinfo import ZoneInfo

from app.config import STATIC_DIR, database_path, upload_directory
from app import notifier
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
    ActivityConfirm,
    ActivityEdit,
    ActivityOut,
    ChatRequest,
    ChatResponse,
    DocumentBlockOut,
    DocumentOut,
    FileUploadOut,
    HealthOut,
    IngestOut,
    LoginIn,
    MessageIn,
    MessageOut,
    ModelChoice,
    ModelSettingsOut,
    ModelSettingsUpdate,
    NotificationOut,
    PreviewActivityOut,
    PreviewIn,
    PreviewOut,
    PushSubscribe,
    PushUnsubscribe,
    ReminderOut,
    ReviewBatchConfirm,
    ReviewBatchOut,
    ReviewItemOut,
    StatusUpdate,
    TrashActivityOut,
)
from app.understanding import (
    chat_with_model,
    teleai_provider_available,
    understand_document,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
LOGGER = logging.getLogger("banwutong")

SESSION_COOKIE = "bwt_session"
GUEST_COOKIE = "bwt_guest"
SESSION_TTL = 30 * 24 * 3600


def _session_signature(payload: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def make_session(username: str, secret: str) -> str:
    payload = f"{username}|{int(time.time()) + SESSION_TTL}"
    return f"{payload}|{_session_signature(payload, secret)}"


def session_is_valid(token: str, username: str, secret: str) -> bool:
    try:
        user, expiry, signature = token.rsplit("|", 2)
        if int(expiry) < time.time():
            return False
        expected = _session_signature(f"{user}|{expiry}", secret)
        return hmac.compare_digest(signature, expected) and user == username
    except (ValueError, TypeError):
        return False


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

        reminder_task: asyncio.Task | None = None
        enabled = os.getenv("BANWUTONG_REMINDERS_DISABLED", "").lower() not in (
            "1",
            "true",
            "yes",
        )
        if enabled:

            async def reminder_loop() -> None:
                while True:
                    try:
                        await asyncio.to_thread(notifier.run_once, repository)
                    except Exception:  # noqa: BLE001 - 提醒失败不能拖垮服务
                        LOGGER.exception("提醒循环出错")
                    await asyncio.sleep(60)

            reminder_task = asyncio.create_task(reminder_loop())

        try:
            yield
        finally:
            if reminder_task is not None:
                reminder_task.cancel()

    app = FastAPI(
        title="班务通 API",
        version="0.1.0",
        description="班级通知理解与报名提醒助手的最小闭环。",
        lifespan=lifespan,
    )
    app.state.repository = repository
    app.state.upload_dir = selected_upload_dir
    app.state.default_model_provider = default_model_provider

    auth_user = os.getenv("BANWUTONG_AUTH_USER", "").strip()
    auth_password = os.getenv("BANWUTONG_AUTH_PASSWORD", "").strip()
    session_secret = (
        os.getenv("BANWUTONG_AUTH_SECRET", "").strip()
        or f"{auth_user}:{auth_password}:banwutong"
    )
    public_paths = {
        "/login",
        "/api/login",
        "/manifest.json",
        "/sw.js",
        "/favicon.ico",
    }

    def is_loopback_direct(request: Request) -> bool:
        forwarded = request.headers.get(
            "cf-connecting-ip"
        ) or request.headers.get("x-forwarded-for")
        client_host = request.client.host if request.client else ""
        host = request.headers.get("host", "").split(":")[0].strip().lower()
        loopback_host = host in {"127.0.0.1", "localhost", "::1", "[::1]"}
        return loopback_host and not forwarded and client_host in {"127.0.0.1", "::1"}

    def basic_is_valid(header: str) -> bool:
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:]).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return False
        user, _, password = decoded.partition(":")
        return secrets.compare_digest(user, auth_user) and secrets.compare_digest(
            password, auth_password
        )

    def is_authenticated(request: Request) -> bool:
        if not auth_user or not auth_password:
            return True
        if is_loopback_direct(request):
            return True
        token = request.cookies.get(SESSION_COOKIE, "")
        if token and session_is_valid(token, auth_user, session_secret):
            return True
        return basic_is_valid(request.headers.get("authorization", ""))

    @app.middleware("http")
    async def require_auth(request: Request, call_next):
        """登录 + 访客只读；本机直连（机器人转发）始终放行。"""
        if not auth_user or not auth_password:
            return await call_next(request)
        path = request.url.path
        if path in public_paths or path.startswith("/static/"):
            return await call_next(request)
        if is_authenticated(request):
            return await call_next(request)
        guest = (
            request.cookies.get(GUEST_COOKIE) == "1"
            or request.query_params.get("guest") == "1"
        )
        # 访客只能读，外加「导入通知」这一个写入口（走本地规则，不花云端额度）。
        if guest and request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        if (
            request.cookies.get(GUEST_COOKIE) == "1"
            and request.method == "POST"
            and path in {"/api/messages", "/api/files", "/api/preview"}
        ):
            return await call_next(request)
        if request.method in {"GET", "HEAD", "OPTIONS"} and path.startswith("/api/"):
            # 未登录也能看到只读接口，但首页仍然先去登录页
            return await call_next(request)
        if request.method == "GET" and "text/html" in request.headers.get(
            "accept", ""
        ):
            return RedirectResponse(url="/login", status_code=302)
        return JSONResponse(
            {"detail": "登录后才能修改", "code": "login_required"},
            status_code=401,
        )

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

    def provider_for(request: Request) -> str:
        """访客只能用本地规则，登录用户才按设置上云端模型。"""
        if not is_authenticated(request):
            return "rules"
        return active_provider()

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
    async def ingest_message(payload: MessageIn, request: Request) -> IngestOut:
        now = datetime.now(SHANGHAI)
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
            now,
            provider_for(request),
        )
        # 闲聊/表情只进「群消息流水」，不建事项卡。
        if understood.kind == "chat":
            repository.record_message(payload, kind="chat")
            return IngestOut(disposition="skipped", activity=None)
        parsed = [item.parsed for item in understood.activities]
        if not parsed:
            parsed = [parse_notification(payload.text, now)]
        results = repository.ingest_many(payload, parsed)
        disposition, activity = results[0]
        return IngestOut(disposition=disposition, activity=activity)

    @app.post("/api/preview", response_model=PreviewOut)
    async def preview_message(payload: PreviewIn) -> PreviewOut:
        """Run deterministic extraction without writing a message or activity."""
        now = datetime.now(SHANGHAI)
        blocks = [
            DocumentBlock(
                locator="preview-1",
                block_type="paragraph",
                text=payload.text,
            )
        ]
        understood = await asyncio.to_thread(
            understand_document,
            blocks,
            now,
            "rules",
        )
        activities = [
            PreviewActivityOut(
                title=item.parsed.title,
                audience=item.parsed.audience,
                deadline=item.parsed.deadline,
                location=item.parsed.location,
                materials=item.parsed.materials,
                registration_url=item.parsed.registration_url,
                contact=item.parsed.contact,
                needs_review=item.parsed.needs_review,
                review_reasons=item.parsed.review_reasons,
            )
            for item in understood.activities
        ]
        return PreviewOut(
            kind="chat" if understood.kind == "chat" else "notice",
            method=understood.method,
            activities=activities,
            note="预览使用本地规则；保存时会按当前模型再次解析。",
        )

    @app.get("/api/messages", response_model=list[MessageOut])
    def list_messages(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[MessageOut]:
        # 群消息流水含原始群聊内容，只给登录用户看。
        if not is_authenticated(request):
            raise HTTPException(status_code=403, detail="群消息流水仅登录用户可见")
        return repository.list_messages(limit)

    @app.post("/api/messages/{message_id}/promote", response_model=IngestOut)
    async def promote_message(message_id: int) -> IngestOut:
        payload = repository.message_input(message_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Message not found")
        now = datetime.now(SHANGHAI)
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
            now,
            active_provider(),
        )
        parsed = [item.parsed for item in understood.activities]
        if not parsed:
            parsed = [parse_notification(payload.text, now)]
        disposition, activity = repository.ingest_many(payload, parsed)[0]
        repository.set_message_kind(message_id, "notice")
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
    async def upload_file(
        request: Request, file: UploadFile = File(...)
    ) -> FileUploadOut:
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

        # OCR 和 PDF 渲染是纯 CPU 活，放线程里跑，别把事件循环卡住
        # （机器人上传大文件时，网页端还要能正常响应）
        extraction = await asyncio.to_thread(extract_document, target, suffix)
        activities: list[ActivityOut] = []
        active_model_provider = provider_for(request)
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

    @app.get("/api/activities/{activity_id}/source")
    def get_activity_source(activity_id: int, request: Request) -> dict:
        # 原文属于群聊内容，只给登录用户看。
        if not is_authenticated(request):
            raise HTTPException(status_code=403, detail="原文仅登录用户可见")
        source = repository.activity_source(activity_id)
        if source is None:
            raise HTTPException(status_code=404, detail="没有找到这张卡片的原文")
        return source

    @app.get("/api/reviews", response_model=list[ReviewItemOut])
    def list_reviews() -> list[ReviewItemOut]:
        return repository.review_queue()

    @app.get(
        "/api/activities/{activity_id}/review",
        response_model=ReviewItemOut,
    )
    def get_activity_review(activity_id: int) -> ReviewItemOut:
        review = repository.get_review(activity_id)
        if review is None:
            raise HTTPException(status_code=404, detail="Activity not found")
        return review

    @app.post(
        "/api/activities/{activity_id}/confirm",
        response_model=ReviewItemOut,
    )
    def confirm_activity(
        activity_id: int,
        payload: ActivityConfirm | None = None,
    ) -> ReviewItemOut:
        confirmation = payload or ActivityConfirm()
        if confirmation.edits and confirmation.edits.deadline:
            if confirmation.edits.deadline.tzinfo is None:
                confirmation.edits.deadline = confirmation.edits.deadline.replace(
                    tzinfo=SHANGHAI
                )
        try:
            review = repository.confirm_activity(activity_id, confirmation)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if review is None:
            raise HTTPException(status_code=404, detail="Activity not found")
        return review

    @app.post("/api/reviews/batch-confirm", response_model=ReviewBatchOut)
    def confirm_reviews_in_batch(payload: ReviewBatchConfirm) -> ReviewBatchOut:
        return repository.confirm_many(payload.activity_ids)

    @app.get("/api/trash", response_model=list[TrashActivityOut])
    def list_trash() -> list[TrashActivityOut]:
        return repository.list_trash()

    @app.delete("/api/trash/{activity_id}", status_code=204)
    def permanently_delete_activity(activity_id: int) -> Response:
        if not repository.purge_activity(activity_id):
            raise HTTPException(status_code=404, detail="Trashed activity not found")
        return Response(status_code=204)

    @app.get("/api/push/public-key")
    def push_public_key() -> dict:
        return {"publicKey": os.getenv("BANWUTONG_VAPID_PUBLIC_KEY", "").strip()}

    @app.post("/api/push/subscribe", status_code=201)
    def push_subscribe(payload: PushSubscribe, request: Request) -> dict:
        repository.add_push_subscription(
            payload.endpoint,
            payload.keys.p256dh,
            payload.keys.auth,
            request.headers.get("user-agent"),
        )
        return {
            "subscribed": True,
            "count": len(repository.list_push_subscriptions()),
        }

    @app.post("/api/push/unsubscribe")
    def push_unsubscribe(payload: PushUnsubscribe) -> dict:
        return {"removed": repository.remove_push_subscription(payload.endpoint)}

    @app.get("/api/notifications", response_model=list[NotificationOut])
    def list_notifications(
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[NotificationOut]:
        return [
            NotificationOut(**row) for row in repository.list_notifications(limit)
        ]

    @app.post("/api/notifications/test")
    def send_test_notification() -> dict:
        subscriptions = repository.list_push_subscriptions()
        if not subscriptions:
            raise HTTPException(status_code=409, detail="还没有已订阅的客户端")
        payload = {
            "title": "班务通测试提醒",
            "body": "如果你看到这条通知，推送链路就是通的。",
            "url": "/",
            "tag": "banwutong-test",
        }
        sent, dead = notifier.send_web_push(subscriptions, payload)
        for endpoint in dead:
            repository.remove_push_subscription(endpoint)
        return {"sent": sent, "dead": len(dead)}

    @app.get("/api/reminders", response_model=list[ReminderOut])
    def list_reminders(
        days: int = Query(default=7, ge=1, le=60),
    ) -> list[ReminderOut]:
        return [
            ReminderOut(activity=activity, due_state=due_state)
            for activity, due_state in repository.reminders(days)
        ]

    @app.get("/api/session")
    def session_state(request: Request) -> dict:
        authenticated = is_authenticated(request)
        return {
            "authenticated": authenticated,
            "guest": not authenticated,
            "auth_required": bool(auth_user and auth_password),
        }

    @app.get("/login", include_in_schema=False)
    def login_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "login.html")

    @app.post("/api/login")
    def login(payload: LoginIn, request: Request) -> Response:
        if not auth_user or not auth_password:
            return JSONResponse({"ok": True})
        if not (
            secrets.compare_digest(payload.username, auth_user)
            and secrets.compare_digest(payload.password, auth_password)
        ):
            raise HTTPException(status_code=401, detail="账号或密码不对")
        scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
        response = JSONResponse({"ok": True})
        response.delete_cookie(GUEST_COOKIE, path="/")
        response.set_cookie(
            SESSION_COOKIE,
            make_session(auth_user, session_secret),
            max_age=SESSION_TTL,
            httponly=True,
            samesite="lax",
            secure=(scheme == "https"),
            path="/",
        )
        return response

    @app.post("/api/logout")
    def logout() -> Response:
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/", include_in_schema=False)
    def index(request: Request, guest: int = 0) -> Response:
        response = FileResponse(STATIC_DIR / "index.html")
        if guest == 1:
            response.set_cookie(
                GUEST_COOKIE,
                "1",
                max_age=SESSION_TTL,
                httponly=True,
                samesite="lax",
                path="/",
            )
        return response

    @app.get("/chat", include_in_schema=False)
    def chat_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "chat.html")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="application/javascript",
            headers={
                "Service-Worker-Allowed": "/",
                "Cache-Control": "no-cache",
            },
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()

