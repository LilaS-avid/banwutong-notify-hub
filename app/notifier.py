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
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import httpx

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
    mark = "【未核对】" if activity.needs_review else ""
    body = (
        f"{deadline.strftime('%m月%d日 %H:%M')} 截止，{_remaining_text(deadline, now)}。"
        f"{('材料：' + '、'.join(activity.materials)) if activity.materials else ''}"
    ).strip()
    if activity.needs_review:
        body = "注意：此截止时间尚未人工核对，可能不准确。\n" + body
    return {
        "title": f"{mark}截止提醒：{activity.title}",
        "body": body,
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


def _webhook_settings() -> tuple[str, str]:
    return (
        os.getenv("BANWUTONG_REMINDER_WEBHOOK_URL", "").strip(),
        os.getenv("BANWUTONG_REMINDER_WEBHOOK_TOKEN", "").strip(),
    )


def _send_webhook(activity: ActivityOut, payload: dict) -> None:
    url, token = _webhook_settings()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.post(
        url,
        headers=headers,
        json={
            "type": "banwutong.reminder",
            "title": payload["title"],
            "text": payload["body"],
            "activity": activity.model_dump(),
        },
        timeout=10,
    )
    response.raise_for_status()


def _smtp_ready() -> bool:
    return bool(
        os.getenv("BANWUTONG_SMTP_HOST", "").strip()
        and os.getenv("BANWUTONG_SMTP_FROM", "").strip()
        and os.getenv("BANWUTONG_SMTP_TO", "").strip()
    )


def _send_email(payload: dict) -> None:
    host = os.getenv("BANWUTONG_SMTP_HOST", "").strip()
    port = int(os.getenv("BANWUTONG_SMTP_PORT", "587") or 587)
    user = os.getenv("BANWUTONG_SMTP_USER", "").strip()
    password = os.getenv("BANWUTONG_SMTP_PASSWORD", "")
    sender = os.getenv("BANWUTONG_SMTP_FROM", "").strip()
    recipients = [
        item.strip()
        for item in os.getenv("BANWUTONG_SMTP_TO", "").split(",")
        if item.strip()
    ]
    use_ssl = os.getenv("BANWUTONG_SMTP_USE_SSL", str(port == 465)).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    message = EmailMessage()
    message["Subject"] = payload["title"]
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(payload["body"])

    client = (
        smtplib.SMTP_SSL(host, port, timeout=15)
        if use_ssl
        else smtplib.SMTP(host, port, timeout=15)
    )
    with client:
        client.ehlo()
        if not use_ssl:
            client.starttls()
            client.ehlo()
        if user:
            client.login(user, password)
        client.send_message(message)


def _channel_names(subscriptions: list[dict]) -> list[str]:
    """Web Push 有订阅就尝试；VAPID 缺失会由发送环节报错。Webhook、邮件只看环境变量。"""
    channels: list[str] = []
    if subscriptions:
        channels.append("webpush")
    if _webhook_settings()[0]:
        channels.append("webhook")
    if _smtp_ready():
        channels.append("email")
    return channels


def run_once(
    repository: ActivityRepository,
    now: datetime | None = None,
) -> list[dict]:
    """扫描一次，把到点的提醒发出去。返回本次发出的记录。"""
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    subscriptions = repository.list_push_subscriptions()
    channels = _channel_names(subscriptions)
    if not channels:
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
            if current >= trigger and current - trigger <= grace
        ]
        if not due:
            continue
        # 同时到点的多条规则只发最近的一条，其余记为 suppressed，避免同一分钟连发。
        due.sort(key=lambda item: item[1], reverse=True)

        for channel in channels:
            pending = [
                item
                for item in due
                if not repository.notification_sent(
                    activity.id,
                    item[0],
                    channel,
                )
            ]
            if not pending:
                continue
            rule = pending[0][0]
            payload = build_payload(activity, rule, deadline, current)
            detail = "ok"
            try:
                if channel == "webpush":
                    sent, dead = send_web_push(subscriptions, payload)
                    for endpoint in dead:
                        repository.remove_push_subscription(endpoint)
                    detail = f"ok={sent}"
                    if sent == 0:
                        continue
                elif channel == "webhook":
                    _send_webhook(activity, payload)
                else:
                    _send_email(payload)
            except Exception as error:  # noqa: BLE001 - 单渠道失败不影响其他渠道
                LOGGER.warning(
                    "提醒发送失败 activity=%s channel=%s error=%s",
                    activity.id,
                    channel,
                    type(error).__name__,
                )
                continue
            for name, _trigger in pending:
                repository.record_notification(
                    activity.id,
                    name,
                    channel=channel,
                    detail=detail if name == rule else "suppressed",
                )
            delivered.append(
                {
                    "activity_id": activity.id,
                    "title": activity.title,
                    "rule": rule,
                    "channel": channel,
                    "sent": 1 if channel != "webpush" else int(detail.split("=")[-1]),
                }
            )
    return delivered
