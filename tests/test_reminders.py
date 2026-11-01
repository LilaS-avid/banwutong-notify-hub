"""截止提醒：到点判定、去重、推送接口。"""
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import app.main as main_module
import app.notifier as notifier
from app.main import create_app
from app.schemas import ActivityOut

SHANGHAI = ZoneInfo("Asia/Shanghai")


def make_activity(
    activity_id: int = 1,
    deadline: str = "2026-11-02T12:00:00+08:00",
    status: str = "open",
) -> ActivityOut:
    return ActivityOut(
        id=activity_id,
        title="英语四级报名",
        audience=None,
        deadline=deadline,
        location=None,
        materials=["学生证"],
        registration_url=None,
        contact=None,
        status=status,
        needs_review=False,
        source_message_id=1,
        created_at="2026-11-01T00:00:00+08:00",
        updated_at="2026-11-01T00:00:00+08:00",
    )


class FakeRepository:
    def __init__(self, activities, subscriptions=None) -> None:
        self.activities = activities
        self.subscriptions = subscriptions if subscriptions is not None else []
        self.records: list[tuple[int, str, str | None]] = []
        self.removed: list[str] = []

    def list_activities(self):
        return self.activities

    def list_push_subscriptions(self):
        return self.subscriptions

    def notification_sent(self, activity_id, rule, channel="webpush"):
        return any(
            item[0] == activity_id and item[1] == rule for item in self.records
        )

    def record_notification(self, activity_id, rule, channel="webpush", detail=None):
        if self.notification_sent(activity_id, rule, channel):
            return False
        self.records.append((activity_id, rule, detail))
        return True

    def remove_push_subscription(self, endpoint):
        self.removed.append(endpoint)
        return True


def test_duplicate_due_rules_send_once(monkeypatch) -> None:
    repo = FakeRepository(
        [make_activity()],
        subscriptions=[{"endpoint": "https://push.example/1", "p256dh": "k", "auth": "a"}],
    )
    sent: list[dict] = []

    def fake_send(subscriptions, payload):
        sent.append(payload)
        return len(subscriptions), []

    monkeypatch.setattr(notifier, "send_web_push", fake_send)

    now = datetime(2026, 11, 2, 9, 0, tzinfo=SHANGHAI)
    first = notifier.run_once(repo, now)
    second = notifier.run_once(repo, now)

    assert len(first) == 1
    assert first[0]["rule"] == "3h"
    assert len(sent) == 1
    assert second == []
    # 同一时刻到点的 8am 也要记下来，否则下一轮会重复发
    rules = {item[1] for item in repo.records}
    assert rules == {"3h", "8am"}


def test_no_subscription_means_no_send(monkeypatch) -> None:
    repo = FakeRepository([make_activity()], subscriptions=[])
    called = []
    monkeypatch.setattr(
        notifier, "send_web_push", lambda *args: called.append(args) or (0, [])
    )

    now = datetime(2026, 11, 2, 9, 0, tzinfo=SHANGHAI)
    assert notifier.run_once(repo, now) == []
    assert called == []


def test_closed_activity_is_skipped(monkeypatch) -> None:
    repo = FakeRepository(
        [make_activity(status="completed")],
        subscriptions=[{"endpoint": "https://push.example/1", "p256dh": "k", "auth": "a"}],
    )
    monkeypatch.setattr(notifier, "send_web_push", lambda *args: (1, []))

    now = datetime(2026, 11, 2, 9, 0, tzinfo=SHANGHAI)
    assert notifier.run_once(repo, now) == []


def test_trigger_outside_grace_is_not_sent(monkeypatch) -> None:
    # 截止在 3 天后：7 天规则早过了宽限窗口，24h/3h 还没到
    repo = FakeRepository(
        [make_activity(deadline="2026-11-05T18:00:00+08:00")],
        subscriptions=[{"endpoint": "https://push.example/1", "p256dh": "k", "auth": "a"}],
    )
    monkeypatch.setattr(notifier, "send_web_push", lambda *args: (1, []))

    now = datetime(2026, 11, 2, 9, 0, tzinfo=SHANGHAI)
    assert notifier.run_once(repo, now) == []


def test_dead_subscription_is_removed(monkeypatch) -> None:
    repo = FakeRepository(
        [make_activity()],
        subscriptions=[{"endpoint": "https://push.example/dead", "p256dh": "k", "auth": "a"}],
    )
    monkeypatch.setattr(notifier, "send_web_push", lambda *args: (0, ["https://push.example/dead"]))

    now = datetime(2026, 11, 2, 9, 0, tzinfo=SHANGHAI)
    assert notifier.run_once(repo, now) == []
    assert repo.removed == ["https://push.example/dead"]


def test_push_endpoints(tmp_path) -> None:
    with TestClient(
        create_app(tmp_path / "push.db", tmp_path / "uploads", default_model_provider="rules")
    ) as client:
        key = client.get("/api/push/public-key").json()["publicKey"]
        assert key

        subscription = {
            "endpoint": "https://push.example/abc",
            "keys": {"p256dh": "p256dh-value", "auth": "auth-value"},
        }
        response = client.post("/api/push/subscribe", json=subscription)
        assert response.status_code == 201
        assert response.json()["count"] == 1

        # 重复订阅同一 endpoint 只保留一条
        assert client.post("/api/push/subscribe", json=subscription).json()["count"] == 1

        assert client.post(
            "/api/push/unsubscribe", json={"endpoint": subscription["endpoint"]}
        ).json()["removed"] is True

        assert client.get("/api/notifications").json() == []

        no_subs = client.post("/api/notifications/test")
        assert no_subs.status_code == 409
