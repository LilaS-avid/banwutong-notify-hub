"""连接层与转换层的衔接测试。

不需要机器人账号、不需要联网：
  - `event_from_message` 用假对象模拟 botpy 的消息对象；
  - botpy 的「全量群消息」补丁只在装了 botpy 时才验证（没装就跳过）。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.qq_adapter import event_from_message, to_message_in


def fake_group_message(content: str = "<@!1020304> 关于四级报名的通知\n报名截止：2026-11-06 12:00"):
    return SimpleNamespace(
        id="msg-1001",
        content=content,
        group_openid="group-openid-9",
        author=SimpleNamespace(member_openid="member-9"),
        timestamp="2026-10-31T09:00:00+08:00",
        attachments=None,
    )


def fake_c2c_message():
    return SimpleNamespace(
        id="msg-1002",
        content="私聊测试",
        author=SimpleNamespace(user_openid="user-9"),
        timestamp="2026-10-31T09:05:00+08:00",
        attachments=None,
    )


def test_group_message_object_round_trips():
    payload = to_message_in(event_from_message(fake_group_message(), "GROUP_AT_MESSAGE_CREATE"))

    assert payload["external_id"] == "msg-1001"
    assert payload["group_id"] == "group-openid-9"
    assert payload["sender_id"] == "member-9"
    assert payload["text"].startswith("关于四级报名的通知")


def test_c2c_message_object_round_trips():
    payload = to_message_in(event_from_message(fake_c2c_message(), "C2C_MESSAGE_CREATE"))

    assert payload["external_id"] == "msg-1002"
    assert payload["group_id"] is None
    assert payload["sender_id"] == "user-9"


def test_full_group_message_event_type_is_supported():
    # 群里不带 @ 的消息也要能转换（群主开了「接收全量消息」才会有这类事件）
    payload = to_message_in(event_from_message(fake_group_message("明天九点开会"), "GROUP_MESSAGE_CREATE"))

    assert payload["text"] == "明天九点开会"


def test_botpy_full_message_parser_patch():
    pytest.importorskip("botpy", reason="未安装 qq-botpy，跳过连接层补丁测试")

    from botpy.connection import ConnectionState

    from scripts.run_qq_bot import _install_full_group_message_support

    _install_full_group_message_support()
    assert hasattr(ConnectionState, "parse_group_message_create"), "botpy 缺少全量群消息解析器时补丁没生效"
