"""登录页与会话 Cookie。"""
import base64

from fastapi.testclient import TestClient

from app.main import create_app


def make_client(tmp_path, monkeypatch, user="teacher", password="secret") -> TestClient:
    monkeypatch.setenv("BANWUTONG_AUTH_USER", user)
    monkeypatch.setenv("BANWUTONG_AUTH_PASSWORD", password)
    return TestClient(
        create_app(tmp_path / "auth.db", tmp_path / "uploads", default_model_provider="rules")
    )


def test_unauthenticated_api_is_rejected(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        assert client.get("/api/activities").status_code == 401


def test_html_navigation_redirects_to_login(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.get(
            "/", headers={"accept": "text/html"}, follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/login"
        assert client.get("/login").status_code == 200


def test_wrong_password_is_rejected(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/login", json={"username": "teacher", "password": "wrong"}
        )
        assert response.status_code == 401
        assert client.get("/api/activities").status_code == 401


def test_login_issues_session_cookie(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post(
            "/api/login", json={"username": "teacher", "password": "secret"}
        )
        assert response.status_code == 200
        assert client.cookies.get("bwt_session")

        assert client.get("/api/activities").status_code == 200
        assert client.get("/", headers={"accept": "text/html"}).status_code == 200


def test_basic_auth_still_works(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        token = base64.b64encode(b"teacher:secret").decode()
        response = client.get(
            "/api/activities", headers={"Authorization": f"Basic {token}"}
        )
        assert response.status_code == 200


def test_logout_clears_session(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        client.post("/api/login", json={"username": "teacher", "password": "secret"})
        assert client.get("/api/activities").status_code == 200

        assert client.post("/api/logout").status_code == 200
        assert client.get("/api/activities").status_code == 401


def test_forged_cookie_is_rejected(tmp_path, monkeypatch) -> None:
    with make_client(tmp_path, monkeypatch) as client:
        client.cookies.set("bwt_session", "teacher|9999999999|deadbeef")
        assert client.get("/api/activities").status_code == 401
