"""截止提醒：到点判定 + Web Push 投递。

设计要点：
- 规则固定为「截止前 7 天 / 24 小时 / 3 小时 / 当天 08:00」，每条活动每个规则只发一次；
- 送达记录写在 notifications 表，(activity_id, rule, channel) 唯一，重启不会重复轰炸；
- 触发时刻已过去太久的规则会被宽限窗口挡掉，避免刚建卡就补发一堆旧提醒；
- 订阅失效（404/410）时删除该订阅，避免持续失败。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.repository import ActivityRepository
from app.schemas import ActivityOut

SHANGHAI = ZoneInfo("Asia/Shanghai")
LOGGER = logging.getLogger("banwutong.notifier")

# (规则名, 提前量, 宽限窗口)
RULES: tuple[tuple[str, timedelta, timedelta], ...] = (
    ("7d", timedelta(days=7), timedelta(days=1)),
    ("24h", timedelta(hours=24), timedelta(hours=6)),
    ("3h", timedelta(hours=3), timedelta(hours=2)),
)
MORNING_RULE = "8am"
MORNING_GRACE = timedelta(hours=12)


def triggers_for(deadline: datetime) -> list[tuple[str, datetime, timedelta]]:
    """返回 [(规则名, 触发时刻, 宽限窗口)]。"""
    items = [
        (name, deadline - lead, grace) for name, lead, grace in RULES
    ]
    morning = deadline.replace(hour=8, minute=0, second=0, microsecond=0)
    if morning < deadline:
        items.append((MORNING_RULE, morning, MORNING_GRACE))
    return items


def _remaining_text(deadline: datetime, now: datetime) -> str:
    delta = deadline - now
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"还剩 {max(minutes, 1)} 分钟"
    hours = minutes // 60
    if hours < 48:
        return f"还剩 {hours} 小时"
    return f"还剩 {hours // 24} 天"


def build_payload(
    activity: ActivityOut,
    rule: str,
    deadline: datetime,
    now: datetime,
) -> dict:
    return {
        "title": f"截止提醒：{activity.title}",
        "body": (
            f"{deadline.strftime('%m月%d日 %H:%M')} 截止，{_remaining_text(deadline, now)}。"
            f"{('材料：' + '、'.join(activity.materials)) if activity.materials else ''}"
        ).strip(),
        "url": "/",
        "tag": f"activity-{activity.id}-{rule}",
        "activity_id": activity.id,
    }


def _vapid_private_key() -> str:
    return os.getenv("BANWUTONG_VAPID_PRIVATE_KEY", "").strip()


def _vapid_subject() -> str:
    return os.getenv("BANWUTONG_VAPID_SUBJECT", "mailto:admin@example.com").strip()


def send_web_push(subscriptions: list[dict], payload: dict) -> tuple[int, list[str]]:
    """发送一条推送，返回 (成功数, 需要删除的失效 endpoint)。"""
    from pywebpush import WebPushException, webpush

    private_key = _vapid_private_key()
    if not private_key:
        raise RuntimeError("BANWUTONG_VAPID_PRIVATE_KEY 未配置")

    sent = 0
    dead: list[str] = []
    body = json.dumps(payload, ensure_ascii=False)
    for item in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": item["endpoint"],
                    "keys": {"p256dh": item["p256dh"], "auth": item["auth"]},
                },
                data=body,
                vapid_private_key=private_key,
                vapid_claims={"sub": _vapid_subject()},
                timeout=15,
            )
            sent += 1
        except WebPushException as error:  # noqa: PERF203
            status = getattr(error.response, "status_code", None)
            if status in (404, 410):
                dead.append(item["endpoint"])
            else:
                LOGGER.warning("webpush 失败 (%s): %s", status, error)
        except Exception as error:  # noqa: BLE001
            LOGGER.warning("webpush 异常：%s", error)
    return sent, dead


def run_once(
    repository: ActivityRepository,
    now: datetime | None = None,
) -> list[dict]:
    """扫描一次，把到点的提醒发出去。返回本次发出的记录。"""
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    subscriptions = repository.list_push_subscriptions()
    if not subscriptions:
        return []

    delivered: list[dict] = []
    for activity in repository.list_activities():
        if activity.status in {"completed", "ignored", "cancelled"}:
            continue
        if not activity.deadline:
            continue
        deadline = datetime.fromisoformat(activity.deadline).astimezone(SHANGHAI)
        if deadline <= current:
            continue
        due = [
            (rule, trigger)
            for rule, trigger, grace in triggers_for(deadline)
            if current >= trigger
            and current - trigger <= grace
            and not repository.notification_sent(activity.id, rule)
        ]
        if not due:
            continue
        # 同时到点的多条规则只发最近的一条，其余记为 suppressed，避免同一分钟连发。
        due.sort(key=lambda item: item[1], reverse=True)
        rule, _ = due[0]
        payload = build_payload(activity, rule, deadline, current)
        sent, dead = send_web_push(subscriptions, payload)
        for endpoint in dead:
            repository.remove_push_subscription(endpoint)
        if sent:
            for name, _trigger in due:
                repository.record_notification(
                    activity.id,
                    name,
                    detail=f"ok={sent}" if name == rule else "suppressed",
                )
            delivered.append(
                {
                    "activity_id": activity.id,
                    "title": activity.title,
                    "rule": rule,
                    "sent": sent,
                }
            )
    return delivered
