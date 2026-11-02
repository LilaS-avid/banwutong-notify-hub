"""一条 QQ 消息的完整处理：文字入库 + 附件解析 + 回执文案。

这里刻意不依赖 botpy：入参只要是「像 botpy 消息对象」的东西（id / content /
group_openid / author / attachments）就行，测试里用 `types.SimpleNamespace` 即可。

流程：
  1. 事件 → 后端消息体（`app/qq_adapter.py`）；
  2. 有文字：POST `/api/messages`（闲聊会被后端判成 chat 并跳过，不建卡）；
  3. 有附件：下载 → POST `/api/files`（后端做 OCR / 文档抽取 / AI 理解）；
  4. 把所有结果拼成一条回执，交给连接层发回群聊。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app import qq_media
from app.qq_adapter import event_from_message, to_message_in

LOGGER = logging.getLogger("banwutong.qq.handler")

# 带附件时，正文太短（多半是「看这个」「急」这类口头语）就不入库，
# 免得给每个附件都配一张没意义的卡。
SHORT_CAPTION_CHARS = 30
MENTION_EVENTS = {"GROUP_AT_MESSAGE_CREATE", "AT_MESSAGE_CREATE"}


class QQHandler:
    """把一条消息处理完，返回要回复的文字（None 表示不回）。"""

    def __init__(
        self,
        api_base: str,
        *,
        client: httpx.AsyncClient | None = None,
        reply_text: str = "created",
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.reply_text = reply_text
        self._client = client

    async def client(self) -> httpx.AsyncClient:
        if self._client is None:
            # 首次处理消息时创建，确保连接池绑在机器人自己的事件循环上
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(180.0, connect=15.0)
            )
        return self._client

    async def handle(self, message: Any, event_type: str) -> str | None:
        event = event_from_message(message, event_type)
        payload = to_message_in(event, require_text=False)
        if payload is None:
            return None

        items = qq_media.attachments_of(event)
        text = payload.get("text") or ""
        if not text and not items:
            return None

        mentioned = event_type in MENTION_EVENTS
        replies: list[str] = []

        if text and (not items or len(text) >= SHORT_CAPTION_CHARS):
            result = await self._post_message(payload)
            if result is not None:
                line = qq_media.describe_text_ingest(result)
                if line and (
                    self.reply_text == "always"
                    or (self.reply_text == "created" and result.get("disposition") == "created")
                ):
                    replies.append(line)
                elif mentioned and result.get("disposition") == "duplicate":
                    replies.append("这条通知之前已经记录过了。")

        if items:
            replies.extend(await self._handle_attachments(items))

        return qq_media.compose_reply(replies) or None

    async def _handle_attachments(self, items: list[qq_media.MediaItem]) -> list[str]:
        client = await self.client()
        results: list[str] = []
        for item in items:
            name = qq_media.resolve_name(item)
            try:
                name, content = await qq_media.download(client, item)
                payload = await qq_media.upload(client, self.api_base, name, content)
                results.append(qq_media.describe_upload(payload, name))
            except qq_media.MediaError as error:
                LOGGER.info("附件处理失败 %s: %s", name, error)
                results.append(f"《{name}》{error.user_message}")
            except httpx.HTTPError as error:
                LOGGER.warning("附件上传失败 %s: %s", name, error)
                results.append(f"《{name}》上传班务通失败，稍后再试。")
        return results

    async def _post_message(self, payload: dict) -> dict | None:
        client = await self.client()
        try:
            response = await client.post(
                f"{self.api_base}/api/messages",
                json=payload,
                timeout=120.0,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            LOGGER.warning("消息入库失败 %s: %s", payload.get("external_id"), error)
            return None
