"""登录页、访客只读与会话 Cookie。"""
import base64

from fastapi.testclient import TestClient

from app.main import create_app


def make_client(tmp_path, monkeypatch, user="teacher", password="secret") -> TestClient:
    monkeypatch.setenv("BANWUTONG_AUTH_USER", user)
    monkeypatch.setenv("BANWUTONG_AUTH_PASSWORD", password)
    return TestClient(
        create_app(tmp_path / "auth.db", tmp_path / "uploads", default_model_provider="rules")
    )


def test_guest_is_read_only(tmp_path, monkeypatch) -> None:
    """访客只能看：导入、上传、预览、撤回、文件与待核对全部挡在登录之后。"""
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/api/activities").status_code == 200

        client.get("/?guest=1", headers={"accept": "text/html"})
        assert client.cookies.get("bwt_guest") == "1"

        assert client.get("/api/activities").status_code == 200
        assert (
            client.post(
                "/api/messages",
                json={
                    "platform": "manual",
                    "external_id": "g-1",
                    "text": "活动名称：创新大赛\n报名截止：2026-11-05 18:00",
                },
            ).status_code
            == 401
        )
        assert (
            client.post("/api/preview", json={"text": "活动名称：创新大赛"}).status_code
            == 401
        )
        assert client.get("/api/files").status_code == 401
        assert client.get("/api/reviews").status_code == 401
        assert (
            client.post(
                "/api/chat", json={"messages": [{"role": "user", "content": "hi"}]}
            ).status_code
            == 401
        )

        # 登录以后才有写权限
        client.post("/api/login", json={"username": "teacher", "password": "secret"})
        imported = client.post(
            "/api/messages",
            json={
                "platform": "manual",
                "external_id": "g-2",
                "text": "活动名称：创新大赛\n报名截止：2026-11-05 18:00",
            },
        )
        assert imported.status_code == 201


def test_guest_cannot_open_ai_chat_page(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        client.get("/?guest=1", headers={"accept": "text/html"})

        response = client.get("/chat", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"

        client.post("/api/login", json={"username": "teacher", "password": "secret"})
        assert client.get("/chat").status_code == 200


def test_guest_cannot_read_message_stream(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        client.get("/?guest=1", headers={"accept": "text/html"})

        assert client.get("/api/messages").status_code == 403

        client.post("/api/login", json={"username": "teacher", "password": "secret"})
        assert client.get("/api/messages").status_code == 200


def test_html_navigation_redirects_to_login(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.get(
            "/", headers={"accept": "text/html"}, follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/login"
        assert client.get("/login").status_code == 200


def test_direct_entry_sets_guest_cookie(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.get(
            "/?guest=1", headers={"accept": "text/html"}, follow_redirects=False
        )
        assert response.status_code == 200
        assert client.cookies.get("bwt_guest") == "1"


def test_wrong_password_is_rejected(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/login", json={"username": "teacher", "password": "wrong"}
        )
        assert response.status_code == 401


def test_login_issues_session_cookie(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/login", json={"username": "teacher", "password": "secret"}
        )
        assert response.status_code == 200
        assert client.cookies.get("bwt_session")

        write = client.post(
            "/api/messages",
            json={"platform": "manual", "external_id": "n-1", "text": "活动名称：测试"},
        )
        assert write.status_code == 201
        assert client.get("/", headers={"accept": "text/html"}).status_code == 200


def test_session_endpoint_reports_state(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        guest = client.get("/api/session").json()
        assert guest["authenticated"] is False
        assert guest["guest"] is True

        client.post("/api/login", json={"username": "teacher", "password": "secret"})
        logged_in = client.get("/api/session").json()
        assert logged_in["authenticated"] is True


def test_basic_auth_still_works(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        token = base64.b64encode(b"teacher:secret").decode()
        response = client.post(
            "/api/messages",
            json={"platform": "manual", "external_id": "b-1", "text": "活动名称：测试"},
            headers={"Authorization": f"Basic {token}"},
        )
        assert response.status_code == 201


def test_logout_drops_write_access(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        client.post("/api/login", json={"username": "teacher", "password": "secret"})
        assert client.post("/api/logout").status_code == 200

        write = client.post(
            "/api/messages",
            json={"platform": "manual", "external_id": "x-1", "text": "活动名称：测试"},
        )
        assert write.status_code == 401


def test_forged_cookie_is_rejected(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        client.cookies.set("bwt_session", "teacher|9999999999|deadbeef")
        write = client.post(
            "/api/messages",
            json={"platform": "manual", "external_id": "f-1", "text": "活动名称：测试"},
        )
        assert write.status_code == 401
