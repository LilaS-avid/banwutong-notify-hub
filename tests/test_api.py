import sqlite3
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from zoneinfo import ZoneInfo

import app.main as main_module
import app.documents as documents_module
from app.main import create_app


NOTICE = """活动名称：创新大赛
报名截止：2026-11-05 18:00
适用对象：全体学生
报名材料：报名表、学生证照片
报名链接：https://example.com/register"""


def make_client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "test.db",
            tmp_path / "uploads",
            default_model_provider="rules",
        )
    )


def test_message_ingestion_is_idempotent(tmp_path) -> None:
    with make_client(tmp_path) as client:
        payload = {
            "platform": "manual",
            "external_id": "message-001",
            "text": NOTICE,
        }
        first = client.post("/api/messages", json=payload)
        second = client.post("/api/messages", json=payload)

        assert first.status_code == 201
        assert first.json()["disposition"] == "created"
        assert second.status_code == 201
        assert second.json()["disposition"] == "duplicate"
        assert len(client.get("/api/activities").json()) == 1


def test_update_merges_into_existing_activity(tmp_path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/api/messages",
            json={"external_id": "message-001", "text": NOTICE},
        )
        updated_notice = NOTICE.replace(
            "报名截止：2026-11-05 18:00",
            "报名截止：2026-11-08 18:00\n材料补充：作品说明",
        )
        result = client.post(
            "/api/messages",
            json={"external_id": "message-002", "text": updated_notice},
        )

        assert result.json()["disposition"] == "updated"
        activities = client.get("/api/activities").json()
        assert len(activities) == 1
        assert activities[0]["deadline"] == "2026-11-08T18:00:00+08:00"
        assert activities[0]["materials"] == ["报名表", "学生证照片", "作品说明"]


def test_complete_and_reminder_state(tmp_path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/api/messages",
            json={"external_id": "message-001", "text": NOTICE},
        ).json()
        activity_id = created["activity"]["id"]

        reminders = client.get("/api/reminders?days=60").json()
        assert reminders[0]["activity"]["id"] == activity_id

        completed = client.patch(
            f"/api/activities/{activity_id}",
            json={"status": "completed"},
        )
        assert completed.status_code == 200
        assert client.get("/api/reminders?days=60").json() == []


def test_notice_without_deadline_is_still_pending(tmp_path) -> None:
    with make_client(tmp_path) as client:
        result = client.post(
            "/api/messages",
            json={"external_id": "message-review", "text": "志愿者招募\n地点：活动中心"},
        )

        assert result.json()["activity"]["status"] == "open"
        assert result.json()["activity"]["needs_review"] is True
        assert len(client.get("/api/activities?status=open").json()) == 1


def test_user_can_edit_activity_content(tmp_path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/api/messages",
            json={"external_id": "message-edit", "text": NOTICE},
        ).json()
        activity_id = created["activity"]["id"]

        edited = client.put(
            f"/api/activities/{activity_id}",
            json={
                "title": "修改后的创新活动",
                "deadline": "2026-12-01T18:00:00",
                "audience": "生物信息学专业学生",
                "materials": ["作品说明"],
                "location": "大学生活动中心",
                "contact": "张老师",
                "registration_url": "https://example.com/updated",
            },
        )

        assert edited.status_code == 200
        activity = edited.json()
        assert activity["title"] == "修改后的创新活动"
        assert activity["deadline"] == "2026-12-01T18:00:00+08:00"
        assert activity["audience"] == "生物信息学专业学生"
        assert activity["materials"] == ["作品说明"]
        assert activity["location"] == "大学生活动中心"
        assert activity["contact"] == "张老师"
        assert activity["registration_url"] == "https://example.com/updated"
        assert activity["status"] == "open"
        assert activity["needs_review"] is False


def test_text_file_upload_creates_activity(tmp_path) -> None:
    with make_client(tmp_path) as client:
        uploaded = client.post(
            "/api/files",
            files={
                "file": (
                    "notice.txt",
                    NOTICE.encode("utf-8"),
                    "text/plain",
                )
            },
        )

        assert uploaded.status_code == 201
        result = uploaded.json()
        assert result["disposition"] == "created"
        assert result["document"]["extract_status"] == "processed"
        assert result["document"]["analysis_method"] == "rules"
        assert result["document"]["block_count"] > 0
        assert result["activity"]["title"] == "创新大赛"
        assert len(result["activities"]) == 1

        documents = client.get("/api/files").json()
        assert len(documents) == 1
        blocks = client.get(
            f"/api/files/{documents[0]['id']}/blocks"
        ).json()
        assert blocks
        assert blocks[0]["locator"]
        download = client.get(
            f"/api/files/{documents[0]['id']}/download"
        )
        assert download.status_code == 200
        assert download.content == NOTICE.encode("utf-8")


def test_duplicate_file_is_not_processed_twice(tmp_path) -> None:
    with make_client(tmp_path) as client:
        first = client.post(
            "/api/files",
            files={"file": ("notice.txt", NOTICE.encode("utf-8"), "text/plain")},
        )
        second = client.post(
            "/api/files",
            files={"file": ("renamed.txt", NOTICE.encode("utf-8"), "text/plain")},
        )

        assert first.json()["disposition"] == "created"
        assert second.json()["disposition"] == "duplicate"
        assert len(second.json()["activities"]) == 1
        assert len(client.get("/api/files").json()) == 1
        assert len(client.get("/api/activities").json()) == 1


class FakeOcrEngine:
    def __call__(self, path: str):
        return (
            [
                [[[0, 0], [100, 0], [100, 20], [0, 20]], "活动名称：图片通知", 0.99],
                [[[0, 30], [100, 30], [100, 50], [0, 50]], "报名截止：2026-11-05 18:00", 0.98],
                [[[0, 60], [100, 60], [100, 80], [0, 80]], "适用对象：全体学生", 0.97],
            ],
            None,
        )


def test_image_ocr_creates_activity(monkeypatch, tmp_path) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    monkeypatch.setattr(documents_module, "_OCR_ENGINE", FakeOcrEngine())
    with make_client(tmp_path) as client:
        result = client.post(
            "/api/files",
            files={"file": ("notice.png", png, "image/png")},
        ).json()

        assert result["document"]["extract_status"] == "processed"
        assert result["activity"]["title"] == "图片通知"
        assert result["activity"]["deadline"] == "2026-11-05T18:00:00+08:00"


def test_image_without_recognizable_text_is_kept(monkeypatch, tmp_path) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    monkeypatch.setattr(
        documents_module,
        "_OCR_ENGINE",
        lambda path: ([], None),
    )
    with make_client(tmp_path) as client:
        result = client.post(
            "/api/files",
            files={"file": ("blank.png", png, "image/png")},
        ).json()

        assert result["document"]["extract_status"] == "failed"
        assert result["activities"] == []


def test_upload_rejects_unsupported_file_type(tmp_path) -> None:
    with make_client(tmp_path) as client:
        result = client.post(
            "/api/files",
            files={"file": ("program.exe", b"MZ", "application/octet-stream")},
        )

        assert result.status_code == 415


def test_one_document_can_create_multiple_activities(tmp_path) -> None:
    content = """活动名称：创新方法讲座
报名截止：2026-11-05 18:00
适用对象：全体学生
报名材料：学生证

活动名称：志愿服务招募
报名截止：2026-11-08 20:00
适用对象：大一学生
报名材料：报名表、身份证照片"""

    with make_client(tmp_path) as client:
        result = client.post(
            "/api/files",
            files={
                "file": (
                    "two-notices.txt",
                    content.encode("utf-8"),
                    "text/plain",
                )
            },
        ).json()

        assert len(result["activities"]) == 2
        assert {item["title"] for item in result["activities"]} == {
            "创新方法讲座",
            "志愿服务招募",
        }
        assert len(client.get("/api/activities").json()) == 2


def test_model_provider_can_be_changed(tmp_path) -> None:
    with make_client(tmp_path) as client:
        initial = client.get("/api/model-settings").json()
        assert initial["provider"] == "rules"
        assert {choice["id"] for choice in initial["choices"]} == {
            "cloud",
            "rules",
        }

        updated = client.put(
            "/api/model-settings",
            json={"provider": "rules"},
        )

        assert updated.status_code == 200
        assert updated.json()["provider"] == "rules"


def test_missing_cloud_model_falls_back_to_rules(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        main_module,
        "teleai_provider_available",
        lambda: False,
    )
    with TestClient(
        create_app(
            tmp_path / "fallback.db",
            tmp_path / "uploads",
            default_model_provider="cloud",
        )
    ) as client:
        settings = client.get("/api/model-settings").json()

        assert settings["provider"] == "rules"


def test_chat_requires_a_model_provider(tmp_path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "你好"}]},
        )

        assert response.status_code == 409


def test_chat_uses_the_selected_model(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        main_module,
        "teleai_provider_available",
        lambda: True,
    )
    monkeypatch.setattr(
        main_module,
        "chat_with_model",
        lambda messages, context, provider: ("当前有一个事项。", "cloud"),
    )
    with TestClient(
        create_app(
            tmp_path / "chat.db",
            tmp_path / "uploads",
            default_model_provider="cloud",
        )
    ) as client:
        response = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "有哪些事项？"}]},
        )

        assert response.status_code == 200
        assert response.json() == {
            "reply": "当前有一个事项。",
            "provider": "cloud",
        }


def test_completed_activity_can_be_deleted_and_restored(tmp_path) -> None:
    with make_client(tmp_path) as client:
        activity_id = client.post(
            "/api/messages",
            json={"external_id": "message-trash", "text": NOTICE},
        ).json()["activity"]["id"]

        rejected = client.delete(f"/api/activities/{activity_id}")
        assert rejected.status_code == 409

        client.patch(
            f"/api/activities/{activity_id}",
            json={"status": "completed"},
        )
        deleted = client.delete(f"/api/activities/{activity_id}")

        assert deleted.status_code == 200
        deleted_activity = deleted.json()
        assert deleted_activity["id"] == activity_id
        deleted_at = datetime.fromisoformat(deleted_activity["deleted_at"])
        purge_after = datetime.fromisoformat(deleted_activity["purge_after"])
        assert purge_after - deleted_at == timedelta(days=7)

        assert client.get("/api/activities").json() == []
        assert [item["id"] for item in client.get("/api/trash").json()] == [
            activity_id
        ]

        restored = client.post(f"/api/activities/{activity_id}/restore")
        assert restored.status_code == 200
        assert restored.json()["status"] == "completed"
        assert client.get("/api/trash").json() == []
        assert len(client.get("/api/activities").json()) == 1


def test_trash_is_purged_after_seven_days(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    with make_client(tmp_path) as client:
        activity_id = client.post(
            "/api/messages",
            json={"external_id": "message-expired", "text": NOTICE},
        ).json()["activity"]["id"]
        client.patch(
            f"/api/activities/{activity_id}",
            json={"status": "completed"},
        )
        client.delete(f"/api/activities/{activity_id}")

        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE activities SET deleted_at = ? WHERE id = ?",
                ((now - timedelta(days=6)).isoformat(), activity_id),
            )
        assert len(client.get("/api/trash").json()) == 1

        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE activities SET deleted_at = ? WHERE id = ?",
                ((now - timedelta(days=7, minutes=1)).isoformat(), activity_id),
            )

        assert client.get("/api/trash").json() == []
        with sqlite3.connect(db_path) as connection:
            activity_count = connection.execute(
                "SELECT COUNT(*) FROM activities WHERE id = ?",
                (activity_id,),
            ).fetchone()[0]
            event_count = connection.execute(
                "SELECT COUNT(*) FROM activity_events WHERE activity_id = ?",
                (activity_id,),
            ).fetchone()[0]
        assert activity_count == 0
        assert event_count == 0


def test_user_can_permanently_delete_trash_item(tmp_path) -> None:
    with make_client(tmp_path) as client:
        activity_id = client.post(
            "/api/messages",
            json={"external_id": "message-purge", "text": NOTICE},
        ).json()["activity"]["id"]
        client.patch(
            f"/api/activities/{activity_id}",
            json={"status": "completed"},
        )
        client.delete(f"/api/activities/{activity_id}")

        purged = client.delete(f"/api/trash/{activity_id}")

        assert purged.status_code == 204
        assert client.get("/api/trash").json() == []
        assert client.post(f"/api/activities/{activity_id}/restore").status_code == 404


def test_existing_database_is_migrated_for_trash(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                audience TEXT,
                deadline TEXT,
                location TEXT,
                materials TEXT NOT NULL DEFAULT '[]',
                registration_url TEXT,
                contact TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                needs_review INTEGER NOT NULL DEFAULT 0,
                source_message_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    with TestClient(create_app(db_path, tmp_path / "uploads")):
        pass

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(activities)")
        }
    assert "deleted_at" in columns



# --- 待核对工作台 -------------------------------------------------------


def _notice_without_deadline() -> str:
    return "志愿者招募\n地点：大学生活动中心"


def _notice_conflict_first() -> str:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    first = now + timedelta(hours=3)
    second = now + timedelta(days=7)
    return (
        "消防演练安排\n"
        f"{first:%Y-%m-%d %H:%M} 在教学楼集合，"
        f"补演安排在 {second:%Y-%m-%d %H:%M}"
    )


def _notice_conflict_second() -> str:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    first = now + timedelta(hours=8)
    second = now + timedelta(days=9)
    return (
        "消防演练安排\n"
        f"{first:%Y-%m-%d %H:%M} 在教学楼集合，"
        f"补演安排在 {second:%Y-%m-%d %H:%M}"
    )


def test_review_queue_lists_missing_deadline_with_evidence(tmp_path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/api/messages",
            json={"external_id": "review-missing", "text": _notice_without_deadline()},
        )

        reviews = client.get("/api/reviews").json()

        assert len(reviews) == 1
        item = reviews[0]
        assert item["activity"]["needs_review"] is True
        assert [reason["code"] for reason in item["reasons"]] == ["deadline_missing"]
        assert item["reasons"][0]["severity"] == "blocking"
        assert item["evidence"][0]["kind"] == "message"
        assert "志愿者招募" in item["evidence"][0]["text"]


def test_review_queue_flags_conflicting_dates(tmp_path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/api/messages",
            json={"external_id": "review-conflict", "text": _notice_conflict_first()},
        )

        reviews = client.get("/api/reviews").json()

        assert len(reviews) == 1
        item = reviews[0]
        assert item["activity"]["deadline"] is not None
        assert "deadline_conflict" in [reason["code"] for reason in item["reasons"]]


def test_confirm_with_corrected_deadline(tmp_path) -> None:
    with make_client(tmp_path) as client:
        activity_id = client.post(
            "/api/messages",
            json={"external_id": "review-confirm", "text": _notice_without_deadline()},
        ).json()["activity"]["id"]

        deadline = (
            datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(hours=5)
        ).isoformat()
        confirmed = client.post(
            f"/api/activities/{activity_id}/confirm",
            json={
                "edits": {
                    "title": "志愿者招募",
                    "deadline": deadline,
                    "audience": "大一学生",
                    "materials": ["报名表"],
                    "location": "大学生活动中心",
                    "contact": None,
                    "registration_url": None,
                }
            },
        )

        assert confirmed.status_code == 200
        review = confirmed.json()
        assert review["activity"]["needs_review"] is False
        assert review["activity"]["reviewed_at"] is not None
        assert review["activity"]["deadline"] == datetime.fromisoformat(
            deadline
        ).astimezone(ZoneInfo("Asia/Shanghai")).isoformat()
        assert client.get("/api/reviews").json() == []


def test_confirmed_review_survives_status_change(tmp_path) -> None:
    """确认状态不能被“标记完成/重新打开”这类操作覆盖掉。"""
    with make_client(tmp_path) as client:
        activity_id = client.post(
            "/api/messages",
            json={"external_id": "review-sticky", "text": _notice_without_deadline()},
        ).json()["activity"]["id"]
        client.post(f"/api/activities/{activity_id}/confirm", json={})

        client.patch(f"/api/activities/{activity_id}", json={"status": "completed"})
        reopened = client.patch(
            f"/api/activities/{activity_id}",
            json={"status": "open"},
        ).json()

        assert reopened["needs_review"] is False
        assert client.get("/api/reviews").json() == []


def test_batch_confirm_skips_blocking_items(tmp_path) -> None:
    with make_client(tmp_path) as client:
        blocking_id = client.post(
            "/api/messages",
            json={"external_id": "batch-blocking", "text": _notice_without_deadline()},
        ).json()["activity"]["id"]
        warning_id = client.post(
            "/api/messages",
            json={"external_id": "batch-warning", "text": _notice_conflict_first()},
        ).json()["activity"]["id"]

        result = client.post(
            "/api/reviews/batch-confirm",
            json={"activity_ids": [blocking_id, warning_id]},
        ).json()

        assert result["confirmed"] == [warning_id]
        assert result["skipped"] == [
            {"activity_id": blocking_id, "reasons": ["deadline_missing"]}
        ]
        remaining = client.get("/api/reviews").json()
        assert [item["activity"]["id"] for item in remaining] == [blocking_id]


def test_changed_deadline_reopens_review(tmp_path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/api/messages",
            json={"external_id": "reopen-1", "text": _notice_conflict_first()},
        )
        activity_id = client.get("/api/reviews").json()[0]["activity"]["id"]
        client.post(f"/api/activities/{activity_id}/confirm", json={})
        assert client.get("/api/reviews").json() == []

        client.post(
            "/api/messages",
            json={"external_id": "reopen-2", "text": _notice_conflict_second()},
        )

        reviews = client.get("/api/reviews").json()
        assert [item["activity"]["id"] for item in reviews] == [activity_id]
        assert reviews[0]["activity"]["reviewed_at"] is None


def test_legacy_database_backfills_review_reasons(tmp_path) -> None:
    db_path = tmp_path / "legacy-review.db"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                external_id TEXT NOT NULL,
                group_id TEXT,
                sender_id TEXT,
                sent_at TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(platform, external_id)
            );
            CREATE TABLE activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                audience TEXT,
                deadline TEXT,
                location TEXT,
                materials TEXT NOT NULL DEFAULT '[]',
                registration_url TEXT,
                contact TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                needs_review INTEGER NOT NULL DEFAULT 0,
                source_message_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO messages(
                platform, external_id, sent_at, raw_text, created_at
            ) VALUES ('manual', 'legacy-1', '2026-10-01T10:00:00+08:00', '旧通知', '2026-10-01T10:00:00+08:00');
            INSERT INTO activities(
                dedupe_key, title, deadline, materials, status, needs_review,
                source_message_id, created_at, updated_at
            ) VALUES ('旧事项', '旧事项', NULL, '[]', 'open', 1, 1,
                      '2026-10-01T10:00:00+08:00', '2026-10-01T10:00:00+08:00');
            """
        )

    with TestClient(create_app(db_path, tmp_path / "uploads")) as client:
        reviews = client.get("/api/reviews").json()

    assert len(reviews) == 1
    assert [reason["code"] for reason in reviews[0]["reasons"]] == ["deadline_missing"]
