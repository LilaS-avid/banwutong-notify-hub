"""附件桥接层（`app/qq_media.py`）的离线测试。

全部用 `httpx.MockTransport`，不联网、不碰真实 QQ 和后端：
  - 平台事件的附件字段能不能正确取出；
  - 没有 filename 时能不能按 content_type 补扩展名；
  - 下载的大小上限、gif 转 png；
  - 上传走的是 multipart，415/413 能不能翻译成人话；
  - 回执文案在「新建 / 重复 / 读不出字 / 超长」几种情况下是否成立。
"""
from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from app import qq_media


def png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def gif_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("P", (2, 2)).save(buffer, format="GIF")
    return buffer.getvalue()


def run(coro):
    return asyncio.run(coro)


def test_attachments_of_reads_platform_dicts():
    event = {
        "t": "GROUP_MESSAGE_CREATE",
        "d": {
            "id": "msg-1",
            "group_openid": "group-1",
            "attachments": [
                {"url": "https://example.com/a.png", "content_type": "image/png", "size": 1024},
                {"url": "https://example.com/b.pdf", "filename": "通知.pdf"},
                {"filename": "没有 url 的坏数据.pdf"},
            ],
        },
    }

    items = qq_media.attachments_of(event)

    assert [item.url for item in items] == [
        "https://example.com/a.png",
        "https://example.com/b.pdf",
    ]
    assert items[0].size == 1024


def test_attachments_of_reads_botpy_objects():
    # botpy 的 _Attachments 是对象，不是 dict
    attachment = SimpleNamespace(
        url="https://example.com/c.jpg",
        filename=None,
        content_type="image/jpeg",
        size=2048,
    )
    event = {"t": "C2C_MESSAGE_CREATE", "d": {"id": "msg-2", "attachments": [attachment]}}

    items = qq_media.attachments_of(event)

    assert items[0].url == "https://example.com/c.jpg"
    assert items[0].content_type == "image/jpeg"


def test_attachments_are_capped_per_message():
    event = {
        "d": {
            "attachments": [
                {"url": f"https://example.com/{index}.png"} for index in range(9)
            ]
        }
    }

    assert len(qq_media.attachments_of(event)) == qq_media.MAX_MEDIA_PER_MESSAGE


def test_missing_filename_gets_suffix_from_content_type():
    item = qq_media.MediaItem(url="https://example.com/x", content_type="image/png")

    assert qq_media.resolve_name(item) == "QQ图片.png"
    assert qq_media.is_supported("QQ图片.png")


def test_missing_filename_for_file_defaults_to_qq_file():
    item = qq_media.MediaItem(
        url="https://example.com/x",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert qq_media.resolve_name(item) == "QQ文件.docx"


def test_filename_without_extension_gets_one():
    item = qq_media.MediaItem(
        url="https://example.com/x",
        filename="奖学金通知",
        content_type="application/pdf",
    )

    assert qq_media.resolve_name(item) == "奖学金通知.pdf"


def test_path_like_filename_is_reduced_to_basename():
    item = qq_media.MediaItem(url="https://example.com/x", filename="../../etc/passwd.txt")

    assert qq_media.resolve_name(item) == "passwd.txt"


def test_unsupported_suffix_is_rejected_before_download():
    item = qq_media.MediaItem(url="https://example.com/x", filename="压缩包.zip")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("不应发起请求")))

    with pytest.raises(qq_media.UnsupportedMedia):
        run(qq_media.download(client, item))


def test_oversized_declared_file_is_rejected_before_download():
    item = qq_media.MediaItem(
        url="https://example.com/big.pdf",
        filename="big.pdf",
        size=qq_media.MAX_MEDIA_BYTES + 1,
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("不应发起请求")))

    with pytest.raises(qq_media.MediaTooLarge):
        run(qq_media.download(client, item))


def test_download_returns_bytes_and_follows_redirect():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == "https://example.com/a.png":
            return httpx.Response(302, headers={"location": "https://cdn.example.com/real.png"})
        return httpx.Response(200, content=png_bytes())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    item = qq_media.MediaItem(url="https://example.com/a.png", content_type="image/png")

    name, content = run(qq_media.download(client, item))

    assert name == "QQ图片.png"
    assert content.startswith(b"\x89PNG")
    assert seen[-1] == "https://cdn.example.com/real.png"


def test_gif_is_converted_to_png():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=gif_bytes()))
    )
    item = qq_media.MediaItem(url="https://example.com/a.gif", filename="表情.gif")

    name, content = run(qq_media.download(client, item))

    assert name == "表情.png"
    with Image.open(BytesIO(content)) as image:
        assert image.format == "PNG"


def test_upload_posts_multipart_and_parses_json():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content
        captured["content_type"] = request.headers.get("content-type", "")
        return httpx.Response(
            201,
            json={
                "disposition": "created",
                "document": {"id": 1, "extract_status": "processed"},
                "activities": [],
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    payload = run(qq_media.upload(client, "http://127.0.0.1:8765", "通知.pdf", b"%PDF-1.4"))

    assert payload["disposition"] == "created"
    assert captured["url"] == "http://127.0.0.1:8765/api/files"
    assert "multipart/form-data" in captured["content_type"]
    assert b'filename="' in captured["body"]
    assert b"%PDF-1.4" in captured["body"]


def test_upload_maps_backend_rejections():
    def make(status: int) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, text="nope"))
        )

    with pytest.raises(qq_media.UnsupportedMedia):
        run(qq_media.upload(make(415), "http://127.0.0.1:8765", "x.zip", b"x"))
    with pytest.raises(qq_media.MediaTooLarge):
        run(qq_media.upload(make(413), "http://127.0.0.1:8765", "x.pdf", b"x"))
    with pytest.raises(qq_media.UploadFailed):
        run(qq_media.upload(make(500), "http://127.0.0.1:8765", "x.pdf", b"x"))


def activity(**overrides) -> dict:
    base = {
        "id": 1,
        "title": "国家励志奖学金评定",
        "deadline": "2026-11-12T23:59:00+08:00",
        "materials": ["申请表", "成绩单"],
        "needs_review": False,
    }
    base.update(overrides)
    return base


def test_describe_upload_lists_activities():
    payload = {
        "disposition": "created",
        "document": {"extract_status": "processed"},
        "activities": [activity()],
    }

    text = qq_media.describe_upload(payload, "通知.pdf")

    assert "通知.pdf" in text
    assert "已交给 AI 解析" in text
    assert "国家励志奖学金评定" in text
    assert "11月12日 23:59" in text
    assert "申请表" in text


def test_describe_upload_marks_review_needed_and_caps_list():
    payload = {
        "disposition": "created",
        "document": {"extract_status": "processed"},
        "activities": [
            activity(id=index, title=f"事项{index}", needs_review=True) for index in range(1, 6)
        ],
    }

    text = qq_media.describe_upload(payload, "通知.png")

    assert "待核对" in text
    assert "事项3" in text
    assert "事项4" not in text
    assert "共 5 项" in text


def test_describe_upload_duplicate_says_already_processed():
    payload = {
        "disposition": "duplicate",
        "document": {"extract_status": "processed"},
        "activities": [activity()],
    }

    text = qq_media.describe_upload(payload, "通知.pdf")

    assert "之前已经处理过" in text
    assert "国家励志奖学金评定" in text


def test_describe_upload_extraction_failed():
    payload = {
        "disposition": "created",
        "document": {"extract_status": "failed"},
        "activities": [],
    }

    text = qq_media.describe_upload(payload, "拍糊了的通知.jpg")

    assert "没能读出文字" in text
    assert "网页端" in text


def test_describe_upload_without_activities():
    payload = {
        "disposition": "created",
        "document": {"extract_status": "processed"},
        "activities": [],
    }

    assert "没有识别出新的待办" in qq_media.describe_upload(payload, "x.txt")


def test_describe_text_ingest_only_reports_created_or_updated():
    created = {
        "disposition": "created",
        "activity": activity(),
    }
    duplicate = {"disposition": "duplicate", "activity": activity()}

    assert qq_media.describe_text_ingest(created).startswith("已记录：国家励志奖学金评定")
    assert qq_media.describe_text_ingest(duplicate) is None


def test_compose_reply_joins_parts_and_truncates():
    assert qq_media.compose_reply(["a", "", None, "b"]) == "a\nb"

    long_reply = qq_media.compose_reply(["字" * (qq_media.MAX_REPLY_CHARS + 50)])

    assert len(long_reply) == qq_media.MAX_REPLY_CHARS
    assert long_reply.endswith("…")
