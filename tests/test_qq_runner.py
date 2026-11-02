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


def test_bot_wires_handlers_and_backend():
    pytest.importorskip("botpy", reason="未安装 qq-botpy，跳过连接层装配测试")

    from scripts.run_qq_bot import build_bot

    bot = build_bot("http://127.0.0.1:8765", dry_run=True, reply_text="always")

    assert bot._handler.api_base == "http://127.0.0.1:8765"
    assert bot._handler.reply_text == "always"
    for name in (
        "on_group_at_message_create",
        "on_group_message_create",
        "on_c2c_message_create",
    ):
        assert hasattr(bot, name), f"缺少事件处理函数 {name}"


class FakeMessage:
    def __init__(self, message_id: str) -> None:
        self.id = message_id
        self.replies: list[dict] = []

    async def reply(self, **kwargs):
        self.replies.append(kwargs)
        return {"id": "sent"}


def test_dispatch_sends_one_reply_and_dedupes_repeat_push():
    pytest.importorskip("botpy", reason="未安装 qq-botpy，跳过分发测试")

    import asyncio

    from scripts.run_qq_bot import build_bot

    bot = build_bot("http://127.0.0.1:8765", dry_run=False)

    class FakeHandler:
        handled = 0

        async def handle(self, message, event_type):
            FakeHandler.handled += 1
            return "已记录：测试通知（截止 11月6日 12:00）"

    bot._handler = FakeHandler()
    message = FakeMessage("msg-1")

    asyncio.run(bot._dispatch(message, "GROUP_MESSAGE_CREATE"))
    asyncio.run(bot._dispatch(message, "GROUP_MESSAGE_CREATE"))

    assert FakeHandler.handled == 1, "同一条消息被平台重推两次，不应处理两次"
    assert message.replies == [
        {"content": "已记录：测试通知（截止 11月6日 12:00）", "msg_seq": 1}
    ]
