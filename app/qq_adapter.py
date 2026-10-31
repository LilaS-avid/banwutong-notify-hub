"""QQ 官方机器人事件 → 班务通标准消息 的转换层。

分工说明：
  - 连接层（连 WebSocket、拿 access_token、收事件）由机器人负责人在自己的
    账号下实现，因为 AppID/AppSecret 和群权限都绑在创建人身上；
  - **本文件只做转换**：把平台推来的事件字典，翻译成后端 `POST /api/messages`
    需要的字段。纯函数、无网络、无凭证，因此任何人（包括没有机器人账号的人）
    都能写、能测、能改。

对应后端契约见 app/schemas.py 的 MessageIn：
  platform / external_id / group_id / sender_id / sent_at / text

用法（拿真实事件或样例事件做回放，不需要机器人账号）：

    python -m app.qq_adapter --replay events.jsonl --dry-run
    python -m app.qq_adapter --replay events.jsonl --post http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# 平台会推送的事件类型；私聊与群聊分开处理
GROUP_EVENTS = {"GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"}
C2C_EVENTS = {"C2C_MESSAGE_CREATE", "AT_MESSAGE_CREATE"}
SUPPORTED = GROUP_EVENTS | C2C_EVENTS

# 群消息里 @机器人 会被前置成 "<@!1234567890>" 这样的提及标记，入库前要去掉
MENTION_PATTERN = re.compile(r"<@!?\d+>\s*")


def _get(data: dict, *keys: str, default: Any = None) -> Any:
    """按顺序取第一个存在的键，兼容平台字段改名。"""
    for key in keys:
        if isinstance(data, dict) and data.get(key) not in (None, ""):
            return data[key]
    return default


def _clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = MENTION_PATTERN.sub("", raw)
    return text.strip()


def _sender_id(author: dict | None) -> str | None:
    if not isinstance(author, dict):
        return None
    # 群成员是 member_openid，私聊是 user_openid，不同事件给的不一样
    return _get(author, "member_openid", "user_openid", "id")


def to_message_in(event: dict) -> dict | None:
    """把一条 QQ 机器人事件转成后端消息体；不支持的事件返回 None。

    external_id 使用平台的消息 ID（`d.id`）。平台会重复推送同一条消息，
    后端按 external_id 幂等，所以重复投递不会重复建卡。
    """
    if not isinstance(event, dict):
        return None

    event_type = _get(event, "t", "type", "event_type", default="")
    if event_type not in SUPPORTED:
        return None

    payload = _get(event, "d", "data", default={}) or {}
    message_id = _get(payload, "id", "msg_id", "message_id")
    if not message_id:
        return None

    text = _clean_text(_get(payload, "content", "text"))
    if not text:
        # 纯图片/附件消息：OCR 还没接进来，现在转成文字只会生成一张叫“[图片]”的垃圾卡片。
        # 直接跳过，等 OCR 通道接好后再处理（见 docs/qq-bot.md「后续」一节）。
        return None

    is_group = event_type in GROUP_EVENTS
    author = _get(payload, "author", default={}) or {}

    return {
        "platform": "qq",
        "external_id": str(message_id),
        "group_id": _get(payload, "group_openid", "group_id") if is_group else None,
        "sender_id": _sender_id(author),
        "sent_at": _get(payload, "timestamp", "sent_at", "time"),
        "text": text,
    }


def iter_events(path: Path):
    """逐行读 JSONL；整份 JSON 数组或单个对象也支持。"""
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return
    if raw.startswith("["):
        for item in json.loads(raw):
            yield item
        return
    for line in raw.splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="把 QQ 机器人事件转换成班务通消息并投递")
    parser.add_argument("--replay", required=True, help="事件文件（JSONL 或 JSON 数组）")
    parser.add_argument("--post", default=None, help="后端地址，如 http://127.0.0.1:8765")
    parser.add_argument("--dry-run", action="store_true", help="只打印转换结果，不发送")
    args = parser.parse_args()

    events = list(iter_events(Path(args.replay)))
    converted, skipped = [], 0
    for event in events:
        message = to_message_in(event)
        if message is None:
            skipped += 1
            continue
        converted.append(message)

    for message in converted:
        print(json.dumps(message, ensure_ascii=False))

    print(f"\n共读取 {len(events)} 条事件，转换 {len(converted)} 条，跳过 {skipped} 条", file=sys.stderr)

    if args.dry_run or not args.post:
        return

    import httpx

    url = args.post.rstrip("/") + "/api/messages"
    with httpx.Client(timeout=30) as client:
        for message in converted:
            response = client.post(url, json=message)
            disposition = ""
            try:
                disposition = response.json().get("disposition", "")
            except ValueError:
                disposition = response.text[:120]
            print(f"{message['external_id']} -> {response.status_code} {disposition}", file=sys.stderr)


if __name__ == "__main__":
    main()
