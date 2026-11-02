"""一条 QQ 消息的处理流程（`app/qq_handler.py`）测试。

用 `httpx.MockTransport` 同时扮演 QQ 文件服务器和班务通后端，
所以这些用例不需要机器人账号、不需要起服务，也不需要真实图片。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx

from app.qq_handler import QQHandler


def run(coro):
    return asyncio.run(coro)


def group_message(content: str = "", attachments: list | None = None):
    return SimpleNamespace(
        id="msg-1001",
        content=content,
        group_openid="group-9",
        author=SimpleNamespace(member_openid="member-9"),
        timestamp="2026-11-02T10:00:00+08:00",
        attachments=attachments or [],
    )


def image_attachment(url: str = "https://img.example/a.png"):
    return SimpleNamespace(
        url=url,
        filename=None,
        content_type="image/png",
        size=1024,
        width=800,
        height=600,
        id="att-1",
    )


def file_upload_payload() -> dict:
    activity = {
        "id": 7,
        "title": "国家励志奖学金评定",
        "deadline": "2026-11-12T23:59:00+08:00",
        "materials": ["申请表"],
        "needs_review": False,
    }
    return {
        "disposition": "created",
        "document": {"id": 3, "extract_status": "processed"},
        "activity": activity,
        "activities": [activity],
    }


class Backend:
    """记录后端收到的请求，并按需返回预设响应。"""

    def __init__(self, *, upload_payload=None, message_payload=None, upload_status=201, message_status=201):
        self.requests: list[tuple[str, str]] = []
        self.upload_payload = upload_payload if upload_payload is not None else file_upload_payload()
        self.message_payload = message_payload or {"disposition": "created", "activity": {"id": 1, "title": "四级报名", "deadline": "2026-11-06T12:00:00+08:00"}}
        self.upload_status = upload_status
        self.message_status = message_status

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, str(request.url)))
        if request.url.host == "img.example":
            return httpx.Response(200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"})
        if request.url.path == "/api/files":
            return httpx.Response(self.upload_status, json=self.upload_payload)
        if request.url.path == "/api/messages":
            return httpx.Response(self.message_status, json=self.message_payload)
        return httpx.Response(404, text="not found")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def test_image_message_is_uploaded_and_receipt_returned():
    backend = Backend()
    handler = QQHandler("http://127.0.0.1:8765", client=backend.client())

    reply = run(handler.handle(group_message(attachments=[image_attachment()]), "GROUP_MESSAGE_CREATE"))

    assert reply is not None
    assert "国家励志奖学金评定" in reply
    assert "11月12日 23:59" in reply
    assert ("GET", "https://img.example/a.png") in backend.requests
    assert ("POST", "http://127.0.0.1:8765/api/files") in backend.requests
    assert ("POST", "http://127.0.0.1:8765/api/messages") not in backend.requests


def test_text_notice_is_ingested_and_receipt_returned():
    backend = Backend()
    handler = QQHandler("http://127.0.0.1:8765", client=backend.client())

    reply = run(
        handler.handle(
            group_message("<@!1020304> 关于四级报名的通知，报名截止 2026-11-06 12:00"),
            "GROUP_AT_MESSAGE_CREATE",
        )
    )

    assert reply == "已记录：四级报名（截止 11月6日 12:00）"
    assert ("POST", "http://127.0.0.1:8765/api/messages") in backend.requests


def test_duplicate_notice_without_mention_stays_silent():
    backend = Backend(message_payload={"disposition": "duplicate", "activity": {"id": 1, "title": "四级报名", "deadline": None}})
    handler = QQHandler("http://127.0.0.1:8765", client=backend.client())

    reply = run(handler.handle(group_message("关于四级报名的通知"), "GROUP_MESSAGE_CREATE"))

    assert reply is None


def test_duplicate_notice_with_mention_gets_a_short_ack():
    backend = Backend(message_payload={"disposition": "duplicate", "activity": {"id": 1, "title": "四级报名", "deadline": None}})
    handler = QQHandler("http://127.0.0.1:8765", client=backend.client())

    reply = run(handler.handle(group_message("关于四级报名的通知"), "GROUP_AT_MESSAGE_CREATE"))

    assert reply == "这条通知之前已经记录过了。"


def test_short_caption_with_attachment_is_not_ingested_as_notice():
    backend = Backend()
    handler = QQHandler("http://127.0.0.1:8765", client=backend.client())

    reply = run(
        handler.handle(
            group_message("看这个", attachments=[image_attachment()]),
            "GROUP_MESSAGE_CREATE",
        )
    )

    assert reply is not None
    assert ("POST", "http://127.0.0.1:8765/api/messages") not in backend.requests


def test_long_caption_with_attachment_is_ingested_too():
    backend = Backend()
    handler = QQHandler("http://127.0.0.1:8765", client=backend.client())
    caption = "关于国家励志奖学金评定工作的通知：请各班于11月12日前把申请表交到辅导员办公室，逾期不再受理。"

    reply = run(
        handler.handle(
            group_message(caption, attachments=[image_attachment()]),
            "GROUP_MESSAGE_CREATE",
        )
    )

    assert ("POST", "http://127.0.0.1:8765/api/messages") in backend.requests
    assert "已记录" in reply
    assert "国家励志奖学金评定" in reply


def test_unsupported_attachment_gets_friendly_hint():
    backend = Backend()
    handler = QQHandler("http://127.0.0.1:8765", client=backend.client())
    attachment = SimpleNamespace(url="https://img.example/a.zip", filename="材料.zip", content_type="application/zip", size=10)

    reply = run(handler.handle(group_message(attachments=[attachment]), "GROUP_MESSAGE_CREATE"))

    assert "材料.zip" in reply
    assert "暂时处理不了" in reply
    assert ("POST", "http://127.0.0.1:8765/api/files") not in backend.requests


def test_backend_failure_does_not_raise():
    backend = Backend(upload_status=500, upload_payload={"detail": "boom"})
    handler = QQHandler("http://127.0.0.1:8765", client=backend.client())

    reply = run(handler.handle(group_message(attachments=[image_attachment()]), "GROUP_MESSAGE_CREATE"))

    assert "上传到班务通失败" in reply


def test_chat_text_is_skipped_silently():
    backend = Backend(message_payload={"disposition": "skipped", "activity": None})
    handler = QQHandler("http://127.0.0.1:8765", client=backend.client())

    reply = run(handler.handle(group_message("哈哈哈"), "GROUP_MESSAGE_CREATE"))

    assert reply is None
