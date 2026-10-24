from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.db import Database
from app.parser import ParsedActivity, normalise_key
from app.schemas import ActivityEdit, ActivityOut, MessageIn


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _now_iso() -> str:
    return datetime.now(SHANGHAI).isoformat()


def _to_activity(row) -> ActivityOut:
    return ActivityOut(
        id=row["id"],
        title=row["title"],
        audience=row["audience"],
        deadline=row["deadline"],
        location=row["location"],
        materials=json.loads(row["materials"] or "[]"),
        registration_url=row["registration_url"],
        contact=row["contact"],
        status=row["status"],
        needs_review=bool(row["needs_review"]),
        source_message_id=row["source_message_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ActivityRepository:
    def __init__(self, database_path: Path) -> None:
        self.database = Database(database_path)

    def initialize(self) -> None:
        self.database.initialize()

    def _message_exists(self, connection, payload: MessageIn) -> int | None:
        row = connection.execute(
            "SELECT id FROM messages WHERE platform = ? AND external_id = ?",
            (payload.platform, payload.external_id),
        ).fetchone()
        return int(row["id"]) if row else None

    def _activity_for_message(self, connection, message_id: int) -> ActivityOut | None:
        row = connection.execute(
            """
            SELECT a.*
            FROM activities a
            JOIN activity_events e ON e.activity_id = a.id
            WHERE e.message_id = ?
            ORDER BY e.id DESC
            LIMIT 1
            """,
            (message_id,),
        ).fetchone()
        return _to_activity(row) if row else None

    def ingest(self, payload: MessageIn, parsed: ParsedActivity) -> tuple[str, ActivityOut]:
        now = _now_iso()
        sent_at_value = payload.sent_at or datetime.now(SHANGHAI)
        if sent_at_value.tzinfo is None:
            sent_at_value = sent_at_value.replace(tzinfo=SHANGHAI)
        sent_at = sent_at_value.astimezone(SHANGHAI).isoformat()

        with self.database.connect() as connection:
            existing_message_id = self._message_exists(connection, payload)
            if existing_message_id is not None:
                activity = self._activity_for_message(connection, existing_message_id)
                if activity is None:
                    raise RuntimeError("Message exists without an activity")
                return "duplicate", activity

            cursor = connection.execute(
                """
                INSERT INTO messages(
                    platform, external_id, group_id, sender_id,
                    sent_at, raw_text, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.platform,
                    payload.external_id,
                    payload.group_id,
                    payload.sender_id,
                    sent_at,
                    payload.text,
                    now,
                ),
            )
            message_id = int(cursor.lastrowid)

            existing = connection.execute(
                "SELECT * FROM activities WHERE dedupe_key = ?",
                (parsed.dedupe_key,),
            ).fetchone()

            if existing:
                existing_materials = json.loads(existing["materials"] or "[]")
                merged_materials = existing_materials + [
                    item for item in parsed.materials if item not in existing_materials
                ]
                merged = {
                    "audience": parsed.audience or existing["audience"],
                    "deadline": parsed.deadline or existing["deadline"],
                    "location": parsed.location or existing["location"],
                    "materials": (
                        json.dumps(merged_materials, ensure_ascii=False)
                        if parsed.materials
                        else existing["materials"]
                    ),
                    "registration_url": (
                        parsed.registration_url or existing["registration_url"]
                    ),
                    "contact": parsed.contact or existing["contact"],
                }
                status = "cancelled" if parsed.change_type == "cancel" else "open"
                merged["needs_review"] = int(merged["deadline"] is None)
                connection.execute(
                    """
                    UPDATE activities
                    SET audience = ?, deadline = ?, location = ?, materials = ?,
                        registration_url = ?, contact = ?, status = ?,
                        needs_review = ?, source_message_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        merged["audience"],
                        merged["deadline"],
                        merged["location"],
                        merged["materials"],
                        merged["registration_url"],
                        merged["contact"],
                        status,
                        merged["needs_review"],
                        message_id,
                        now,
                        existing["id"],
                    ),
                )
                activity_id = int(existing["id"])
                disposition = "updated"
            else:
                status = "cancelled" if parsed.change_type == "cancel" else "open"
                cursor = connection.execute(
                    """
                    INSERT INTO activities(
                        dedupe_key, title, audience, deadline, location, materials,
                        registration_url, contact, status, needs_review,
                        source_message_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        parsed.dedupe_key,
                        parsed.title,
                        parsed.audience,
                        parsed.deadline,
                        parsed.location,
                        json.dumps(parsed.materials, ensure_ascii=False),
                        parsed.registration_url,
                        parsed.contact,
                        status,
                        int(parsed.needs_review),
                        message_id,
                        now,
                        now,
                    ),
                )
                activity_id = int(cursor.lastrowid)
                disposition = "created"

            connection.execute(
                """
                INSERT INTO activity_events(activity_id, message_id, change_type, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (activity_id, message_id, parsed.change_type, now),
            )
            row = connection.execute(
                "SELECT * FROM activities WHERE id = ?",
                (activity_id,),
            ).fetchone()
            return disposition, _to_activity(row)

    def list_activities(self, status: str | None = None) -> list[ActivityOut]:
        with self.database.connect() as connection:
            if status:
                rows = connection.execute(
                    """
                    SELECT * FROM activities
                    WHERE status = ?
                    ORDER BY
                        CASE WHEN deadline IS NULL THEN 1 ELSE 0 END,
                        deadline ASC,
                        id DESC
                    """,
                    (status,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM activities
                    ORDER BY
                        CASE WHEN deadline IS NULL THEN 1 ELSE 0 END,
                        deadline ASC,
                        id DESC
                    """
                ).fetchall()
        return [_to_activity(row) for row in rows]

    def set_status(self, activity_id: int, status: str) -> ActivityOut | None:
        now = _now_iso()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE activities
                SET status = ?,
                    needs_review = CASE WHEN deadline IS NULL THEN 1 ELSE 0 END,
                    updated_at = ?
                WHERE id = ?
                """,
                (status, now, activity_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM activities WHERE id = ?",
                (activity_id,),
            ).fetchone()
            return _to_activity(row)

    def update_details(
        self,
        activity_id: int,
        payload: ActivityEdit,
    ) -> ActivityOut | None:
        now = _now_iso()
        deadline = payload.deadline.isoformat() if payload.deadline else None
        key = normalise_key(payload.title) or "unnamed"
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM activities WHERE id = ?",
                (activity_id,),
            ).fetchone()
            if existing is None:
                return None
            try:
                connection.execute(
                    """
                    UPDATE activities
                    SET dedupe_key = ?, title = ?, audience = ?, deadline = ?,
                        location = ?, materials = ?, registration_url = ?,
                        contact = ?, needs_review = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        key,
                        payload.title,
                        payload.audience,
                        deadline,
                        payload.location,
                        json.dumps(payload.materials, ensure_ascii=False),
                        payload.registration_url,
                        payload.contact,
                        int(deadline is None),
                        now,
                        activity_id,
                    ),
                )
            except Exception as error:
                if "UNIQUE constraint failed" in str(error):
                    raise ValueError("Another activity already uses this title") from error
                raise
            row = connection.execute(
                "SELECT * FROM activities WHERE id = ?",
                (activity_id,),
            ).fetchone()
            return _to_activity(row)

    def reminders(self, days: int = 7) -> list[tuple[ActivityOut, str]]:
        now = datetime.now(SHANGHAI)
        horizon = now + timedelta(days=days)
        result: list[tuple[ActivityOut, str]] = []
        for activity in self.list_activities():
            if activity.status in {"completed", "ignored", "cancelled"}:
                continue
            if not activity.deadline:
                continue
            deadline = datetime.fromisoformat(activity.deadline).astimezone(SHANGHAI)
            if deadline < now:
                state = "overdue"
            elif deadline.date() == now.date():
                state = "today"
            elif deadline <= horizon:
                state = "upcoming"
            else:
                continue
            result.append((activity, state))
        return result

