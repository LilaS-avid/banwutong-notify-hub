from fastapi.testclient import TestClient

from app.main import create_app


NOTICE = """活动名称：创新大赛
报名截止：2026-11-05 18:00
适用对象：全体学生
报名材料：报名表、学生证照片
报名链接：https://example.com/register"""


def make_client(tmp_path) -> TestClient:
    return TestClient(create_app(tmp_path / "test.db"))


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

