"""群消息流水：闲聊不建卡，但留档并可手动提卡。"""
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import create_app
from app.understanding import UnderstandingResult


def make_client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "test.db",
            tmp_path / "uploads",
            default_model_provider="rules",
        )
    )


def _fake_understanding(kind: str):
    def fake(blocks, now=None, provider=None):  # noqa: ANN001
        if kind == "chat":
            return UnderstandingResult(method="cloud", activities=[], kind="chat")
        # notice 但模型没抽出字段时，接口应回退到规则解析
        return UnderstandingResult(method="cloud", activities=[], kind="notice")

    return fake


def test_chat_message_is_recorded_without_card(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main_module, "understand_document", _fake_understanding("chat"))
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/messages",
            json={
                "platform": "qq",
                "external_id": "chat-001",
                "group_id": "G1",
                "sender_id": "S1",
                "text": "收到，谢谢老师",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["disposition"] == "skipped"
        assert body["activity"] is None
        assert client.get("/api/activities").json() == []

        messages = client.get("/api/messages").json()
        assert len(messages) == 1
        assert messages[0]["kind"] == "chat"
        assert messages[0]["text"] == "收到，谢谢老师"
        assert messages[0]["activity_id"] is None


def test_notice_message_creates_card_and_marks_stream(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main_module, "understand_document", _fake_understanding("notice"))
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/messages",
            json={
                "platform": "qq",
                "external_id": "notice-001",
                "text": "活动名称：创新大赛\n报名截止：2026-11-05 18:00",
            },
        )

        assert response.status_code == 201
        assert response.json()["disposition"] == "created"
        messages = client.get("/api/messages").json()
        assert messages[0]["kind"] == "notice"
        assert messages[0]["activity_id"] == response.json()["activity"]["id"]


def test_promote_chat_message_creates_card(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(main_module, "understand_document", _fake_understanding("chat"))
    with make_client(tmp_path) as client:
        client.post(
            "/api/messages",
            json={
                "platform": "qq",
                "external_id": "chat-002",
                "text": "明天上午十点带学生证到教务处",
            },
        )
        message_id = client.get("/api/messages").json()[0]["id"]

        promoted = client.post(f"/api/messages/{message_id}/promote")

        assert promoted.status_code == 200
        assert promoted.json()["disposition"] == "created"
        assert promoted.json()["activity"]["title"]
        assert len(client.get("/api/activities").json()) == 1

        messages = client.get("/api/messages").json()
        assert messages[0]["kind"] == "notice"
        assert messages[0]["activity_id"] == promoted.json()["activity"]["id"]


def test_promote_missing_message_returns_404(tmp_path) -> None:
    with make_client(tmp_path) as client:
        assert client.post("/api/messages/999/promote").status_code == 404
