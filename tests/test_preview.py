from fastapi.testclient import TestClient

from app.main import create_app


def test_preview_extracts_without_persisting(tmp_path) -> None:
    app = create_app(
        tmp_path / "preview.db",
        tmp_path / "uploads",
        default_model_provider="rules",
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/preview",
            json={
                "text": (
                    "活动名称：校园智能体应用创新大赛\n"
                    "报名截止：2026-11-05 18:00\n"
                    "报名材料：报名表、学生证照片\n"
                    "报名链接：https://www.hrbmu.edu.cn/"
                )
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["kind"] == "notice"
        assert payload["activities"][0]["title"] == "校园智能体应用创新大赛"
        assert payload["activities"][0]["materials"] == ["报名表", "学生证照片"]
        assert payload["activities"][0]["deadline"].startswith("2026-11-05")
        assert client.get("/api/activities").json() == []
        assert client.get("/api/messages").json() == []


def test_preview_rejects_blank_text(tmp_path) -> None:
    app = create_app(
        tmp_path / "preview-blank.db",
        tmp_path / "uploads",
        default_model_provider="rules",
    )
    with TestClient(app) as client:
        response = client.post("/api/preview", json={"text": "   "})

    assert response.status_code == 422
