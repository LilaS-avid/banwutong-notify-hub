"""QQ 机器人事件转换层的测试。

这些用例**不需要机器人账号**：用官方文档的事件结构造样例，验证"平台事件 → 后端消息"
的字段映射。等真实报文到手后，把真实事件补进 `REAL_EVENTS` 再跑一遍即可。

覆盖点：
  - 群里 @机器人 的消息（content 前置 <@!...> 提及标记，必须去掉）
  - 群里不带 @ 的全量消息
  - 私聊消息
  - 纯图片消息（无文字、只有附件）
  - 平台重复推送同一条消息（external_id 必须一致，交给后端幂等）
  - 无关事件类型（必须跳过，不能抛异常）
"""
from __future__ import annotations

import json

from app.qq_adapter import to_message_in

GROUP_AT_EVENT = {
    "id": "event-001",
    "op": 0,
    "t": "GROUP_AT_MESSAGE_CREATE",
    "d": {
        "id": "msg-abc-001",
        "content": "<@!1020304>  关于四级报名的通知\n报名截止：2026-11-06 12:00",
        "group_openid": "group-openid-01",
        "author": {"id": "member-001", "member_openid": "member-openid-01"},
        "timestamp": "2026-10-31T09:00:00+08:00",
    },
}

GROUP_MESSAGE_EVENT = {
    "t": "GROUP_MESSAGE_CREATE",
    "d": {
        "id": "msg-abc-002",
        "content": "明天九点到，需要观看一个视频",
        "group_openid": "group-openid-01",
        "author": {"member_openid": "member-openid-02"},
        "timestamp": "2026-10-31T09:05:00+08:00",
    },
}

C2C_EVENT = {
    "t": "C2C_MESSAGE_CREATE",
    "d": {
        "id": "msg-c2c-001",
        "content": "测试一下",
        "author": {"user_openid": "user-openid-01"},
        "timestamp": "2026-10-31T09:10:00+08:00",
    },
}

IMAGE_ONLY_EVENT = {
    "t": "GROUP_MESSAGE_CREATE",
    "d": {
        "id": "msg-abc-003",
        "content": "",
        "group_openid": "group-openid-01",
        "author": {"member_openid": "member-openid-03"},
        "attachments": [{"url": "https://example.com/a.png", "content_type": "image/png"}],
        "timestamp": "2026-10-31T09:15:00+08:00",
    },
}


def test_group_at_message_strips_mention():
    message = to_message_in(GROUP_AT_EVENT)

    assert message["platform"] == "qq"
    assert message["external_id"] == "msg-abc-001"
    assert message["group_id"] == "group-openid-01"
    assert message["sender_id"] == "member-openid-01"
    assert message["text"].startswith("关于四级报名的通知")
    assert "<@!" not in message["text"]
    assert message["sent_at"] == "2026-10-31T09:00:00+08:00"


def test_group_message_without_at():
    message = to_message_in(GROUP_MESSAGE_EVENT)

    assert message["external_id"] == "msg-abc-002"
    assert message["group_id"] == "group-openid-01"
    assert message["text"] == "明天九点到，需要观看一个视频"


def test_c2c_message_has_no_group():
    message = to_message_in(C2C_EVENT)

    assert message["external_id"] == "msg-c2c-001"
    assert message["group_id"] is None
    assert message["sender_id"] == "user-openid-01"


def test_image_only_message_is_skipped():
    # 没接 OCR 之前，纯图片消息转成文字只会生成一张叫“[图片]”的垃圾卡片，直接跳过
    assert to_message_in(IMAGE_ONLY_EVENT) is None


def test_duplicate_push_keeps_same_external_id():
    # 平台会重复推送同一条消息，external_id 必须稳定，后端才能按它幂等
    first = to_message_in(GROUP_AT_EVENT)
    second = to_message_in(json.loads(json.dumps(GROUP_AT_EVENT)))

    assert first["external_id"] == second["external_id"]


def test_unsupported_event_is_skipped():
    assert to_message_in({"t": "GROUP_ADD_ROBOT", "d": {}}) is None
    assert to_message_in({}) is None
    assert to_message_in({"t": "GROUP_MESSAGE_CREATE", "d": {}}) is None


def test_empty_content_is_skipped():
    assert to_message_in({"t": "GROUP_MESSAGE_CREATE", "d": {"id": "msg-x", "content": "  "}}) is None
