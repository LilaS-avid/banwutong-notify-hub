from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.db import Database
from app.documents import DocumentBlock
from app.parser import ParsedActivity, normalise_key
from app.review import describe_reasons, has_blocking_reason, sanitise_reasons
from app.schemas import (
    ActivityConfirm,
    ActivityEdit,
    ActivityOut,
    DocumentBlockOut,
    DocumentOut,
    MessageIn,
    ReviewBatchOut,
    ReviewEvidenceOut,
    ReviewItemOut,
    ReviewSkipOut,
    MessageOut,
    TrashActivityOut,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
TRASH_RETENTION = timedelta(days=7)
DOCUMENT_SELECT = """
SELECT d.*,
       (SELECT COUNT(*) FROM document_blocks b WHERE b.document_id = d.id)
       AS block_count
FROM documents d
"""
MESSAGE_SELECT = """
SELECT m.*,
       (SELECT MIN(e.activity_id) FROM activity_events e WHERE e.message_id = m.id)
       AS activity_id
FROM messages m
"""


PLATFORM_LABELS = {
    "manual": "手动导入",
    "qq": "QQ 群消息",
    "wecom": "企业微信",
    "email": "邮件",
    "file": "上传文件",
}


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
        review_reasons=list(json.loads(row["review_reasons"] or "[]")),
        reviewed_at=row["reviewed_at"],
        source_message_id=row["source_message_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_trash_activity(row) -> TrashActivityOut:
    deleted_at = datetime.fromisoformat(row["deleted_at"])
    if deleted_at.tzinfo is None:
        deleted_at = deleted_at.replace(tzinfo=SHANGHAI)
    purge_after = deleted_at.astimezone(SHANGHAI) + TRASH_RETENTION
    return TrashActivityOut(
        **_to_activity(row).model_dump(),
        deleted_at=deleted_at.astimezone(SHANGHAI).isoformat(),
        purge_after=purge_after.isoformat(),
    )


def _to_message(row) -> MessageOut:
    kind = (row["kind"] or "notice").strip().lower()
    return MessageOut(
        id=row["id"],
        platform=row["platform"],
        text=row["raw_text"],
        kind="chat" if kind == "chat" else "notice",
        sent_at=row["sent_at"],
        sender_id=row["sender_id"],
        activity_id=row["activity_id"],
        created_at=row["created_at"],
    )


def _to_document(row) -> DocumentOut:
    return DocumentOut(
        id=row["id"],
        original_name=row["original_name"],
        media_type=row["media_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        extract_status=row["extract_status"],
        extract_note=row["extract_note"],
        analysis_method=row["analysis_method"],
        block_count=int(row["block_count"]),
        activity_id=row["activity_id"],
        created_at=row["created_at"],
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

    def _activities_for_message(
        self,
        connection,
        message_id: int,
    ) -> list[ActivityOut]:
        rows = connection.execute(
            """
            SELECT DISTINCT a.*
            FROM activities a
            JOIN activity_events e ON e.activity_id = a.id
            WHERE e.message_id = ?
            ORDER BY a.id
            """,
            (message_id,),
        ).fetchall()
        return [_to_activity(row) for row in rows]

    def ingest(self, payload: MessageIn, parsed: ParsedActivity) -> tuple[str, ActivityOut]:
        return self.ingest_many(payload, [parsed])[0]

    def _message(self, connection, message_id: int) -> MessageOut | None:
        row = connection.execute(
            MESSAGE_SELECT + " WHERE m.id = ?",
            (message_id,),
        ).fetchone()
        return _to_message(row) if row else None

    def record_message(self, payload: MessageIn, kind: str = "chat") -> MessageOut:
        """只登记消息、不建事项卡（闲聊/表情走这条路）。"""
        now = _now_iso()
        sent_at_value = payload.sent_at or datetime.now(SHANGHAI)
        if sent_at_value.tzinfo is None:
            sent_at_value = sent_at_value.replace(tzinfo=SHANGHAI)
        sent_at = sent_at_value.astimezone(SHANGHAI).isoformat()
        with self.database.connect() as connection:
            existing = self._message_exists(connection, payload)
            if existing is not None:
                connection.execute(
                    "UPDATE messages SET kind = ? WHERE id = ?",
                    (kind, existing),
                )
                return self._message(connection, existing)
            cursor = connection.execute(
                """
                INSERT INTO messages(
                    platform, external_id, group_id, sender_id,
                    sent_at, raw_text, kind, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.platform,
                    payload.external_id,
                    payload.group_id,
                    payload.sender_id,
                    sent_at,
                    payload.text,
                    kind,
                    now,
                ),
            )
            message_id = int(cursor.lastrowid)
        return self.get_message(message_id)

    def get_message(self, message_id: int) -> MessageOut | None:
        with self.database.connect() as connection:
            return self._message(connection, message_id)

    def message_input(self, message_id: int) -> MessageIn | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?",
                (message_id,),
            ).fetchone()
        if row is None:
            return None
        return MessageIn(
            platform=row["platform"],
            external_id=row["external_id"],
            group_id=row["group_id"],
            sender_id=row["sender_id"],
            sent_at=datetime.fromisoformat(row["sent_at"]),
            text=row["raw_text"],
        )

    def list_messages(self, limit: int = 50) -> list[MessageOut]:
        with self.database.connect() as connection:
            rows = connection.execute(
                MESSAGE_SELECT + " ORDER BY m.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_to_message(row) for row in rows]

    def set_message_kind(self, message_id: int, kind: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE messages SET kind = ? WHERE id = ?",
                (kind, message_id),
            )

    def ingest_many(
        self,
        payload: MessageIn,
        parsed_activities: list[ParsedActivity],
    ) -> list[tuple[str, ActivityOut]]:
        if not parsed_activities:
            raise ValueError("At least one parsed activity is required")
        now = _now_iso()
        sent_at_value = payload.sent_at or datetime.now(SHANGHAI)
        if sent_at_value.tzinfo is None:
            sent_at_value = sent_at_value.replace(tzinfo=SHANGHAI)
        sent_at = sent_at_value.astimezone(SHANGHAI).isoformat()

        with self.database.connect() as connection:
            existing_message_id = self._message_exists(connection, payload)
            if existing_message_id is not None:
                activities = self._activities_for_message(
                    connection,
                    existing_message_id,
                )
                if activities:
                    return [("duplicate", activity) for activity in activities]
                message_id = existing_message_id
            else:
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

            results: list[tuple[str, ActivityOut]] = []
            for parsed in parsed_activities:
                results.append(
                    self._upsert_activity(connection, message_id, parsed, now)
                )
            return results

    def _upsert_activity(
        self,
        connection,
        message_id: int,
        parsed: ParsedActivity,
        now: str,
    ) -> tuple[str, ActivityOut]:
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
                reasons = [
                    code
                    for code in parsed.review_reasons
                    if code != "deadline_missing"
                ]
                if merged["deadline"] is None:
                    reasons.insert(0, "deadline_missing")
                reasons = sanitise_reasons(reasons)
                reviewed_at = existing["reviewed_at"]
                if reviewed_at and existing["deadline"] != merged["deadline"]:
                    # 截止时间被新通知改写，原来的人工确认不再成立。
                    reviewed_at = None
                merged["needs_review"] = int(bool(reasons) and reviewed_at is None)
                connection.execute(
                    """
                    UPDATE activities
                    SET audience = ?, deadline = ?, location = ?, materials = ?,
                        registration_url = ?, contact = ?, status = ?,
                        needs_review = ?, review_reasons = ?, reviewed_at = ?,
                        source_message_id = ?, updated_at = ?
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
                        json.dumps(reasons, ensure_ascii=False),
                        reviewed_at,
                        message_id,
                        now,
                        existing["id"],
                    ),
                )
                activity_id = int(existing["id"])
                disposition = "updated"
            else:
                status = "cancelled" if parsed.change_type == "cancel" else "open"
                reasons = sanitise_reasons(list(parsed.review_reasons))
                cursor = connection.execute(
                    """
                    INSERT INTO activities(
                        dedupe_key, title, audience, deadline, location, materials,
                        registration_url, contact, status, needs_review,
                        review_reasons, source_message_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        int(bool(reasons)),
                        json.dumps(reasons, ensure_ascii=False),
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
                    WHERE status = ? AND deleted_at IS NULL
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
                    WHERE deleted_at IS NULL
                    ORDER BY
                        CASE WHEN deadline IS NULL THEN 1 ELSE 0 END,
                        deadline ASC,
                        id DESC
                    """
                ).fetchall()
        return [_to_activity(row) for row in rows]

    def get_activity(self, activity_id: int) -> ActivityOut | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM activities WHERE id = ? AND deleted_at IS NULL",
                (activity_id,),
            ).fetchone()
            return _to_activity(row) if row else None

    def set_status(self, activity_id: int, status: str) -> ActivityOut | None:
        now = _now_iso()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE activities
                SET status = ?, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
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
        with self.database.connect() as connection:
            return self._write_details(connection, activity_id, payload)

    def _write_details(
        self,
        connection,
        activity_id: int,
        payload: ActivityEdit,
    ) -> ActivityOut | None:
        now = _now_iso()
        deadline = payload.deadline.isoformat() if payload.deadline else None
        key = normalise_key(payload.title) or "unnamed"
        existing = connection.execute(
            """
            SELECT id, reviewed_at FROM activities
            WHERE id = ? AND deleted_at IS NULL
            """,
            (activity_id,),
        ).fetchone()
        if existing is None:
            return None
        # 人工改过字段后只保留结构性判断：原文层的区间/多日期歧义
        # 已由这次人工输入消解，不再重复报警。
        reasons: list[str] = []
        if deadline is None:
            reasons.append("deadline_missing")
        if key == "unnamed":
            reasons.append("title_missing")
        try:
            connection.execute(
                """
                UPDATE activities
                SET dedupe_key = ?, title = ?, audience = ?, deadline = ?,
                    location = ?, materials = ?, registration_url = ?,
                    contact = ?, needs_review = ?, review_reasons = ?,
                    updated_at = ?
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
                    int(bool(reasons) and existing["reviewed_at"] is None),
                    json.dumps(reasons, ensure_ascii=False),
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

    def review_queue(self) -> list[ReviewItemOut]:
        """待核对队列：需要人工确认且未删除的事项，缺截止时间的排最前。"""
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM activities
                WHERE deleted_at IS NULL
                  AND needs_review = 1
                  AND status IN ('open', 'cancelled')
                ORDER BY
                    CASE WHEN deadline IS NULL THEN 0 ELSE 1 END,
                    deadline ASC,
                    id DESC
                """
            ).fetchall()
            return [self._to_review_item(connection, row) for row in rows]

    def get_review(self, activity_id: int) -> ReviewItemOut | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM activities WHERE id = ? AND deleted_at IS NULL",
                (activity_id,),
            ).fetchone()
            return self._to_review_item(connection, row) if row else None

    def confirm_activity(
        self,
        activity_id: int,
        payload: ActivityConfirm,
    ) -> ReviewItemOut | None:
        now = _now_iso()
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM activities WHERE id = ? AND deleted_at IS NULL",
                (activity_id,),
            ).fetchone()
            if existing is None:
                return None
            if payload.edits is not None:
                if self._write_details(connection, activity_id, payload.edits) is None:
                    return None
            connection.execute(
                """
                UPDATE activities
                SET needs_review = 0, reviewed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, activity_id),
            )
            row = connection.execute(
                "SELECT * FROM activities WHERE id = ?",
                (activity_id,),
            ).fetchone()
            return self._to_review_item(connection, row)

    def confirm_many(self, activity_ids: list[int]) -> ReviewBatchOut:
        """批量确认低风险事项；带 blocking 原因的会被跳过并回传。"""
        now = _now_iso()
        confirmed: list[int] = []
        skipped: list[ReviewSkipOut] = []
        with self.database.connect() as connection:
            for activity_id in dict.fromkeys(activity_ids):
                row = connection.execute(
                    "SELECT * FROM activities WHERE id = ? AND deleted_at IS NULL",
                    (activity_id,),
                ).fetchone()
                if row is None:
                    skipped.append(
                        ReviewSkipOut(
                            activity_id=activity_id,
                            reasons=["activity_not_found"],
                        )
                    )
                    continue
                reasons = list(json.loads(row["review_reasons"] or "[]"))
                if not row["needs_review"]:
                    confirmed.append(activity_id)
                    continue
                if has_blocking_reason(reasons):
                    skipped.append(
                        ReviewSkipOut(
                            activity_id=activity_id,
                            reasons=sanitise_reasons(reasons),
                        )
                    )
                    continue
                connection.execute(
                    """
                    UPDATE activities
                    SET needs_review = 0, reviewed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, now, activity_id),
                )
                confirmed.append(activity_id)
        return ReviewBatchOut(confirmed=confirmed, skipped=skipped)

    def _to_review_item(self, connection, row) -> ReviewItemOut:
        activity = _to_activity(row)
        return ReviewItemOut(
            activity=activity,
            reasons=describe_reasons(activity.review_reasons),
            evidence=self._evidence_for(connection, row),
        )

    def _evidence_for(self, connection, row) -> list[ReviewEvidenceOut]:
        evidence: list[ReviewEvidenceOut] = []
        message = connection.execute(
            "SELECT platform, raw_text FROM messages WHERE id = ?",
            (row["source_message_id"],),
        ).fetchone()
        if message is not None:
            evidence.append(
                ReviewEvidenceOut(
                    kind="message",
                    label=PLATFORM_LABELS.get(
                        message["platform"],
                        str(message["platform"]),
                    ),
                    text=str(message["raw_text"])[:4_000],
                )
            )
        quotes = connection.execute(
            """
            SELECT d.original_name, m.quote
            FROM activity_mentions m
            JOIN documents d ON d.id = m.document_id
            WHERE m.activity_id = ?
            ORDER BY m.id
            """,
            (row["id"],),
        ).fetchall()
        seen: set[str] = set()
        for quote in quotes:
            text = str(quote["quote"])
            if text in seen:
                continue
            seen.add(text)
            evidence.append(
                ReviewEvidenceOut(
                    kind="document",
                    label=str(quote["original_name"]),
                    text=text,
                )
            )
        return evidence

    def soft_delete(self, activity_id: int) -> TrashActivityOut | None:
        now = datetime.now(SHANGHAI)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM activities WHERE id = ? AND deleted_at IS NULL",
                (activity_id,),
            ).fetchone()
            if row is None:
                return None
            if row["status"] != "completed":
                raise ValueError("Only completed activities can be deleted")
            connection.execute(
                """
                UPDATE activities
                SET deleted_at = ?, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (now.isoformat(), now.isoformat(), activity_id),
            )
            deleted = connection.execute(
                "SELECT * FROM activities WHERE id = ?",
                (activity_id,),
            ).fetchone()
            return _to_trash_activity(deleted)

    def list_trash(self) -> list[TrashActivityOut]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM activities
                WHERE deleted_at IS NOT NULL
                ORDER BY deleted_at DESC, id DESC
                """
            ).fetchall()
            return [_to_trash_activity(row) for row in rows]

    def restore_activity(self, activity_id: int) -> ActivityOut | None:
        now = _now_iso()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE activities
                SET deleted_at = NULL, updated_at = ?
                WHERE id = ? AND deleted_at IS NOT NULL
                """,
                (now, activity_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM activities WHERE id = ?",
                (activity_id,),
            ).fetchone()
            return _to_activity(row)

    @staticmethod
    def _purge_rows(connection, activity_ids: list[int]) -> int:
        if not activity_ids:
            return 0
        placeholders = ", ".join("?" for _ in activity_ids)
        parameters = tuple(activity_ids)
        connection.execute(
            f"DELETE FROM activity_mentions WHERE activity_id IN ({placeholders})",
            parameters,
        )
        connection.execute(
            f"DELETE FROM document_activity_links WHERE activity_id IN ({placeholders})",
            parameters,
        )
        connection.execute(
            f"UPDATE documents SET activity_id = NULL WHERE activity_id IN ({placeholders})",
            parameters,
        )
        connection.execute(
            f"DELETE FROM activity_events WHERE activity_id IN ({placeholders})",
            parameters,
        )
        cursor = connection.execute(
            f"DELETE FROM activities WHERE id IN ({placeholders})",
            parameters,
        )
        return cursor.rowcount

    def purge_activity(self, activity_id: int) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM activities
                WHERE id = ? AND deleted_at IS NOT NULL
                """,
                (activity_id,),
            ).fetchone()
            if row is None:
                return False
            self._purge_rows(connection, [activity_id])
            return True

    def purge_expired(self, now: datetime | None = None) -> int:
        current = now or datetime.now(SHANGHAI)
        if current.tzinfo is None:
            current = current.replace(tzinfo=SHANGHAI)
        cutoff = (current.astimezone(SHANGHAI) - TRASH_RETENTION).isoformat()
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM activities
                WHERE deleted_at IS NOT NULL AND deleted_at <= ?
                """,
                (cutoff,),
            ).fetchall()
            activity_ids = [int(row["id"]) for row in rows]
            return self._purge_rows(connection, activity_ids)

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

    # ---- 推送订阅与送达记录 ----

    def add_push_subscription(
        self,
        endpoint: str,
        p256dh: str,
        auth: str,
        user_agent: str | None = None,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO push_subscriptions(
                    endpoint, p256dh, auth, user_agent, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(endpoint) DO UPDATE SET
                    p256dh = excluded.p256dh,
                    auth = excluded.auth,
                    user_agent = excluded.user_agent
                """,
                (endpoint, p256dh, auth, user_agent, _now_iso()),
            )

    def remove_push_subscription(self, endpoint: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = ?",
                (endpoint,),
            )
            return cursor.rowcount > 0

    def list_push_subscriptions(self) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM push_subscriptions ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def notification_sent(
        self,
        activity_id: int,
        rule: str,
        channel: str = "webpush",
    ) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM notifications
                WHERE activity_id = ? AND rule = ? AND channel = ?
                """,
                (activity_id, rule, channel),
            ).fetchone()
        return row is not None

    def record_notification(
        self,
        activity_id: int,
        rule: str,
        channel: str = "webpush",
        detail: str | None = None,
    ) -> bool:
        with self.database.connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO notifications(
                        activity_id, rule, channel, detail, sent_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (activity_id, rule, channel, detail, _now_iso()),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def list_notifications(self, limit: int = 50) -> list[dict]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM notifications ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_document_by_hash(self, sha256: str) -> DocumentOut | None:
        with self.database.connect() as connection:
            row = connection.execute(
                DOCUMENT_SELECT + " WHERE d.sha256 = ?",
                (sha256,),
            ).fetchone()
            return _to_document(row) if row else None

    def create_document(
        self,
        *,
        original_name: str,
        stored_name: str,
        media_type: str | None,
        size_bytes: int,
        sha256: str,
        extract_status: str,
        extract_note: str | None,
        analysis_method: str,
        extracted_text: str | None,
        message_id: int | None,
        activity_id: int | None,
    ) -> DocumentOut:
        now = _now_iso()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO documents(
                    original_name, stored_name, media_type, size_bytes, sha256,
                    extract_status, extract_note, analysis_method, extracted_text,
                    message_id, activity_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    original_name,
                    stored_name,
                    media_type,
                    size_bytes,
                    sha256,
                    extract_status,
                    extract_note,
                    analysis_method,
                    extracted_text,
                    message_id,
                    activity_id,
                    now,
                ),
            )
            row = connection.execute(
                DOCUMENT_SELECT + " WHERE d.id = ?",
                (int(cursor.lastrowid),),
            ).fetchone()
            return _to_document(row)

    def list_documents(self) -> list[DocumentOut]:
        with self.database.connect() as connection:
            rows = connection.execute(
                DOCUMENT_SELECT + " ORDER BY d.id DESC"
            ).fetchall()
            return [_to_document(row) for row in rows]

    def get_document(self, document_id: int) -> DocumentOut | None:
        with self.database.connect() as connection:
            row = connection.execute(
                DOCUMENT_SELECT + " WHERE d.id = ?",
                (document_id,),
            ).fetchone()
            return _to_document(row) if row else None

    def get_document_stored_name(self, document_id: int) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT stored_name FROM documents WHERE id = ?",
                (document_id,),
            ).fetchone()
            return str(row["stored_name"]) if row else None

    def get_setting(self, key: str) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_settings WHERE key = ?",
                (key,),
            ).fetchone()
            return str(row["value"]) if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, _now_iso()),
            )

    def save_document_structure(
        self,
        document_id: int,
        blocks: list[DocumentBlock],
        activity_ids: list[int],
        evidence_by_activity: dict[int, list[str]],
    ) -> None:
        with self.database.connect() as connection:
            block_ids: dict[str, int] = {}
            for ordinal, block in enumerate(blocks, start=1):
                cursor = connection.execute(
                    """
                    INSERT INTO document_blocks(
                        document_id, locator, block_type, text, ordinal
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        block.locator,
                        block.block_type,
                        block.text,
                        ordinal,
                    ),
                )
                block_ids[block.locator] = int(cursor.lastrowid)

            for activity_id in dict.fromkeys(activity_ids):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO document_activity_links(
                        document_id, activity_id
                    ) VALUES (?, ?)
                    """,
                    (document_id, activity_id),
                )

            for activity_id, locators in evidence_by_activity.items():
                for locator in locators:
                    block_id = block_ids.get(locator)
                    block = next(
                        (item for item in blocks if item.locator == locator),
                        None,
                    )
                    if block_id is None or block is None:
                        continue
                    connection.execute(
                        """
                        INSERT INTO activity_mentions(
                            document_id, block_id, activity_id, quote
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (document_id, block_id, activity_id, block.text[:500]),
                    )

    def list_document_blocks(self, document_id: int) -> list[DocumentBlockOut]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, locator, block_type, text, ordinal
                FROM document_blocks
                WHERE document_id = ?
                ORDER BY ordinal
                """,
                (document_id,),
            ).fetchall()
            return [
                DocumentBlockOut(
                    id=row["id"],
                    locator=row["locator"],
                    block_type=row["block_type"],
                    text=row["text"],
                    ordinal=row["ordinal"],
                )
                for row in rows
            ]

    def list_document_activities(self, document_id: int) -> list[ActivityOut]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT a.*
                FROM activities a
                JOIN document_activity_links l ON l.activity_id = a.id
                WHERE l.document_id = ? AND a.deleted_at IS NULL
                ORDER BY a.id
                """,
                (document_id,),
            ).fetchall()
            return [_to_activity(row) for row in rows]

