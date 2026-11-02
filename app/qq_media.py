"""QQ 机器人收到的附件（图片/文件）→ 班务通 `/api/files` 的桥接层。

分工：
  - 本文件只负责「从事件里取附件 → 下载 → 转交后端 → 组织中文回执」；
  - 识别与理解全部在班务通后端（OCR + 文档抽取 + AI 解析），机器人不重复实现。

网络调用都通过外部传入的 `httpx.AsyncClient`，测试时可以换成
`httpx.MockTransport`，因此本模块不需要真实 QQ 账号也能完整验证。

平台侧事实（见 docs/qq-bot.md「附件」一节）：
  - 图片、文件都通过事件的 `d.attachments` 下发，不是 `message_type`；
  - 每个附件有 `url`（带签名的临时链接）、`filename`（可能为空）、
    `content_type`、`size`；
  - 链接可能过期，所以收到后要尽快下载，不要只存 URL。
"""
from __future__ import annotations

import logging
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

from app.documents import ALLOWED_SUFFIXES

LOGGER = logging.getLogger("banwutong.qq.media")

# 与后端 /api/files 的上限保持一致；超了后端也是 413，不如本地先挡掉
MAX_MEDIA_BYTES = 20 * 1024 * 1024
# 一条消息最多处理这么多个附件，防止有人一次甩 50 张图把机器人拖死
MAX_MEDIA_PER_MESSAGE = 5
# 群聊一条消息的字数上限保守取值，太长会被平台截断或直接拒收
MAX_REPLY_CHARS = 900

# 平台经常只给 content_type 不给扩展名；后端按扩展名收文件，必须补齐
CONTENT_TYPE_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "application/json": ".json",
    "text/html": ".html",
    "application/rtf": ".rtf",
    "text/rtf": ".rtf",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel.sheet.macroenabled.12": ".xlsm",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}

SUPPORTED_SUFFIXES = set(ALLOWED_SUFFIXES) | {".gif"}
_UNSAFE_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(slots=True)
class MediaItem:
    """事件里的一条附件。字段名与平台一致，缺失就是 None。"""

    url: str
    filename: str | None = None
    content_type: str | None = None
    size: int | None = None


class MediaError(Exception):
    """可以直接翻译给群成员看的附件错误。"""

    user_message = "处理失败。"

    def __init__(self, name: str, detail: str = "") -> None:
        super().__init__(detail or name)
        self.name = name


class UnsupportedMedia(MediaError):
    user_message = (
        "这种格式暂时处理不了。PDF、Word、Excel、PPT、TXT/MD/CSV/HTML/RTF "
        "和图片都行。"
    )


class MediaTooLarge(MediaError):
    user_message = "文件超过 20MB，班务通暂时收不了，麻烦压缩后再发。"


class DownloadFailed(MediaError):
    user_message = "文件下载失败了（链接可能已过期），麻烦重新发一次。"


class UploadFailed(MediaError):
    user_message = "上传到班务通失败了，稍后再试。"


def _field(item: Any, name: str) -> Any:
    """附件可能是平台原始 dict，也可能是 botpy 的 `_Attachments` 对象。"""
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def attachments_of(event: dict) -> list[MediaItem]:
    """取出事件里的附件清单（最多 MAX_MEDIA_PER_MESSAGE 条）。"""
    payload = event.get("d") or {}
    raw = payload.get("attachments") or []
    items: list[MediaItem] = []
    for entry in raw:
        url = _field(entry, "url")
        if not url:
            continue
        size = _field(entry, "size")
        try:
            parsed_size = int(size) if size is not None else None
        except (TypeError, ValueError):
            parsed_size = None
        items.append(
            MediaItem(
                url=str(url),
                filename=_field(entry, "filename"),
                content_type=_field(entry, "content_type"),
                size=parsed_size,
            )
        )
    return items[:MAX_MEDIA_PER_MESSAGE]


def _default_stem(content_type: str | None) -> str:
    media_type = (content_type or "").split(";")[0].strip().lower()
    return "QQ图片" if media_type.startswith("image/") else "QQ文件"


def resolve_name(item: MediaItem) -> str:
    """决定交给后端时用的文件名：能保留原名就保留，缺扩展名就按类型补。"""
    raw = (item.filename or "").strip().replace("\\", "/")
    name = Path(raw).name if raw else ""
    name = _UNSAFE_NAME_CHARS.sub("_", name)[:150].strip() or _default_stem(item.content_type)
    suffix = Path(name).suffix.lower()
    if suffix:
        return name
    media_type = (item.content_type or "").split(";")[0].strip().lower()
    guessed = CONTENT_TYPE_SUFFIXES.get(media_type, "")
    return f"{name}{guessed}" if guessed else name


def is_supported(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED_SUFFIXES


def _gif_to_png(name: str, content: bytes) -> tuple[str, bytes]:
    """QQ 表情包常见 gif；后端只认 png/jpg/webp，取首帧转 png 再交过去。"""
    if Path(name).suffix.lower() != ".gif":
        return name, content
    try:
        from PIL import Image

        with Image.open(BytesIO(content)) as image:
            image.seek(0)
            buffer = BytesIO()
            image.convert("RGB").save(buffer, format="PNG")
        return str(Path(name).with_suffix(".png")), buffer.getvalue()
    except Exception as error:  # noqa: BLE001 - 转码失败按不支持处理
        raise UnsupportedMedia(name, f"gif 转码失败：{error}") from error


def _guess_mime(name: str) -> str:
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


async def download(
    client: httpx.AsyncClient,
    item: MediaItem,
    *,
    limit: int = MAX_MEDIA_BYTES,
) -> tuple[str, bytes]:
    """下载附件，返回 (规范化后的文件名, 内容)。"""
    name = resolve_name(item)
    if not is_supported(name):
        raise UnsupportedMedia(name)
    if item.size is not None and item.size > limit:
        raise MediaTooLarge(name, f"声明大小 {item.size} 字节")
    try:
        response = await client.get(item.url, follow_redirects=True)
    except httpx.HTTPError as error:
        raise DownloadFailed(name, str(error)) from error
    if response.status_code >= 400:
        raise DownloadFailed(name, f"HTTP {response.status_code}")
    content = response.content
    if not content:
        raise DownloadFailed(name, "响应为空")
    if len(content) > limit:
        raise MediaTooLarge(name, f"实际大小 {len(content)} 字节")
    name, content = _gif_to_png(name, content)
    return name, content


async def upload(
    client: httpx.AsyncClient,
    api_base: str,
    name: str,
    content: bytes,
    *,
    timeout: float = 180.0,
) -> dict:
    """把文件交给后端 `/api/files`，由它做 OCR、抽取和 AI 理解。"""
    files = {"file": (name, content, _guess_mime(name))}
    try:
        response = await client.post(
            f"{api_base.rstrip('/')}/api/files",
            files=files,
            timeout=timeout,
        )
    except httpx.HTTPError as error:
        raise UploadFailed(name, str(error)) from error
    if response.status_code == 415:
        raise UnsupportedMedia(name, response.text[:200])
    if response.status_code == 413:
        raise MediaTooLarge(name, response.text[:200])
    if response.status_code >= 400:
        raise UploadFailed(name, f"HTTP {response.status_code}: {response.text[:200]}")
    try:
        return response.json()
    except ValueError as error:  # noqa: BLE001
        raise UploadFailed(name, "后端返回的不是 JSON") from error


def _format_deadline(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        moment = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return str(raw)
    text = f"{moment.month}月{moment.day}日 {moment.hour:02d}:{moment.minute:02d}"
    if moment.year != datetime.now().year:
        text = f"{moment.year}年{text}"
    return text


def _activity_line(activity: dict, index: int) -> str:
    parts = [str(activity.get("title") or "未命名事项")]
    deadline = _format_deadline(activity.get("deadline"))
    parts.append(f"截止 {deadline}" if deadline else "截止时间未识别")
    materials = [str(item) for item in (activity.get("materials") or []) if item]
    if materials:
        parts.append("材料 " + "、".join(materials[:4]))
    if activity.get("needs_review"):
        parts.append("待核对")
    return f"{index}）" + "｜".join(parts)


def describe_upload(payload: dict, name: str) -> str:
    """把 `/api/files` 的返回翻译成群聊里能读的一两句话。"""
    document = payload.get("document") or {}
    activities = payload.get("activities") or []
    duplicate = payload.get("disposition") == "duplicate"

    if activities:
        head = (
            f"《{name}》之前已经处理过，识别到 {len(activities)} 项："
            if duplicate
            else f"《{name}》已交给 AI 解析，识别到 {len(activities)} 项："
        )
        lines = [head]
        lines.extend(
            _activity_line(activity, index)
            for index, activity in enumerate(activities[:3], start=1)
        )
        if len(activities) > 3:
            lines.append(f"…共 {len(activities)} 项，完整列表见班务通网页端。")
        return "\n".join(lines)

    if document.get("extract_status") == "failed":
        if duplicate:
            return f"《{name}》之前收到过，但没能读出里面的文字。可以到班务通网页端手动补充。"
        return (
            f"《{name}》收到了，但没能读出文字（可能拍得不够清楚，或这份格式暂不支持）。"
            "文件已经存档，可以到班务通网页端手动补充。"
        )
    if duplicate:
        return f"《{name}》之前已经处理过了，没有新的待办。"
    return f"《{name}》已存档，没有识别出新的待办事项。"


def describe_text_ingest(payload: dict) -> str | None:
    """文字通知入库后的回执；闲聊/重复消息返回 None（不回复，避免刷屏）。"""
    activity = payload.get("activity") or {}
    if not activity:
        return None
    title = str(activity.get("title") or "").strip()
    if not title:
        return None
    deadline = _format_deadline(activity.get("deadline"))
    tail = f"截止 {deadline}" if deadline else "截止时间未识别"
    disposition = payload.get("disposition")
    if disposition == "created":
        return f"已记录：{title}（{tail}）"
    if disposition == "updated":
        return f"已更新：{title}（{tail}）"
    return None


def compose_reply(parts: list[str]) -> str:
    text = "\n".join(part.strip() for part in parts if part and part.strip())
    if len(text) > MAX_REPLY_CHARS:
        text = text[: MAX_REPLY_CHARS - 1].rstrip() + "…"
    return text
