from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from zoneinfo import ZoneInfo

from app.config import STATIC_DIR, database_path
from app.parser import parse_notification
from app.repository import ActivityRepository
from app.schemas import (
    ActivityEdit,
    ActivityOut,
    HealthOut,
    IngestOut,
    MessageIn,
    ReminderOut,
    StatusUpdate,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")


def create_app(db_path: str | Path | None = None) -> FastAPI:
    repository = ActivityRepository(Path(db_path) if db_path else database_path())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository.initialize()
        yield

    app = FastAPI(
        title="班务通 API",
        version="0.1.0",
        description="班级通知理解与报名提醒助手的最小闭环。",
        lifespan=lifespan,
    )
    app.state.repository = repository

    @app.get("/health", response_model=HealthOut)
    def health() -> HealthOut:
        return HealthOut(status="ok", service="banwutong")

    @app.post("/api/messages", response_model=IngestOut, status_code=201)
    def ingest_message(payload: MessageIn) -> IngestOut:
        parsed = parse_notification(payload.text, datetime.now(SHANGHAI))
        disposition, activity = repository.ingest(payload, parsed)
        return IngestOut(disposition=disposition, activity=activity)

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

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()

