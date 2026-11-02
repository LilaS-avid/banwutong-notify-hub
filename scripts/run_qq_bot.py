"""QQ 机器人连接层：连上 QQ，收发消息，把图片/文件交给班务通处理。

分工：
  - 本文件负责 **连接与收发**（鉴权、WebSocket、心跳、回复），要有 AppID/AppSecret；
  - `app/qq_adapter.py` 负责 **转换**（平台事件 → 后端消息），纯逻辑、无凭证；
  - `app/qq_media.py` 负责 **附件**（下载 / 上传 / 回执文案）；
  - `app/qq_handler.py` 负责 **一条消息的完整处理**。

运行前准备（AppID/AppSecret 在 QQ 开放平台控制台，个人主体即可创建）：

    # .env
    QQBOT_APPID=你的AppID
    QQBOT_SECRET=你的AppSecret
    BANWUTONG_API=http://127.0.0.1:8765

启动：

    pip install -r requirements-bot.txt
    python -m scripts.run_qq_bot

只想看收到的消息、不写库也不回复（排查用）：

    python -m scripts.run_qq_bot --dry-run

注意：botpy 1.2.1 本身没有 `GROUP_MESSAGE_CREATE`（群内全量消息）的解析器，
本文件在启动时补了一个，否则群里不 @ 机器人的通知会被当成未知事件丢掉。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from collections import OrderedDict
from pathlib import Path

from dotenv import load_dotenv

# 先加载项目根目录的 .env，否则 QQBOT_APPID / QQBOT_SECRET 读不到
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 重复推送的同一条消息只处理一次（平台会重推，后端虽然幂等，但回复会重复）
SEEN_MESSAGE_LIMIT = 500


def _install_full_group_message_support() -> None:
    """给 botpy 补上「群内全量消息」事件。

    botpy 的 `ConnectionState` 在初始化时扫描自身的 `parse_*` 方法建事件表，
    官方版本只提供了 `parse_group_at_message_create`（@ 消息），没有全量消息。
    这里补一个同名规则的方法，平台一旦推 `GROUP_MESSAGE_CREATE` 就能被分发。
    """
    from botpy.connection import ConnectionState
    from botpy.message import GroupMessage

    if hasattr(ConnectionState, "parse_group_message_create"):
        return

    def parse_group_message_create(self, payload):  # noqa: ANN001
        message = GroupMessage(self.api, payload.get("id"), payload.get("d", {}))
        self._dispatch("group_message_create", message)

    ConnectionState.parse_group_message_create = parse_group_message_create


def _ensure_event_loop() -> None:
    """botpy 的 Client 在构造时就会 `asyncio.get_event_loop()`。

    Python 3.12 里，如果这个线程之前跑过 `asyncio.run()`（测试里很常见），
    当前循环已被置空，直接构造 Client 会抛 RuntimeError；这里补一个。
    """
    import warnings

    with warnings.catch_warnings():
        # 3.12 里「隐式创建事件循环」会发 DeprecationWarning，日志里很难看
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            asyncio.get_event_loop_policy().get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())


def build_bot(
    api_base: str,
    dry_run: bool,
    sandbox: bool = False,
    debug: bool = False,
    reply_text: str = "created",
):
    from botpy import Client, Intents

    from app.qq_adapter import event_from_message
    from app.qq_handler import QQHandler

    _ensure_event_loop()

    class BanwutongBot(Client):
        def __init__(self, *, handler: QQHandler, dry_run: bool, **kwargs):
            super().__init__(**kwargs)
            self._handler = handler
            self._dry_run = dry_run
            self._seen: OrderedDict[str, None] = OrderedDict()

        async def on_ready(self):
            print("机器人已上线，图片/文件会自动交给班务通解析", flush=True)

        async def _dispatch(self, message, event_type: str) -> None:
            message_id = str(getattr(message, "id", "") or "")
            if message_id:
                if message_id in self._seen:
                    return
                self._seen[message_id] = None
                while len(self._seen) > SEEN_MESSAGE_LIMIT:
                    self._seen.popitem(last=False)

            if self._dry_run:
                event = event_from_message(message, event_type)
                print(
                    json.dumps(event, ensure_ascii=False, default=str),
                    flush=True,
                )
                return

            try:
                reply = await self._handler.handle(message, event_type)
            except Exception as error:  # noqa: BLE001 - 单条消息失败不能让机器人掉线
                print(
                    f"[{event_type}] 处理消息失败：{type(error).__name__}: {error}",
                    file=sys.stderr,
                    flush=True,
                )
                return

            if reply:
                await self._reply(message, event_type, reply)

        async def _reply(self, message, event_type: str, text: str) -> None:
            try:
                # msg_id + msg_seq 组成被动回复；同一条消息最多回 5 次，有效期 5 分钟。
                # 一条消息只回一次，所以 msg_seq 固定 1。
                await message.reply(content=text, msg_seq=1)
                print(f"[{event_type}] 已回复 {len(text)} 字", flush=True)
            except Exception as error:  # noqa: BLE001
                print(
                    f"[{event_type}] 回复失败：{type(error).__name__}: {error}",
                    file=sys.stderr,
                    flush=True,
                )

        async def on_group_at_message_create(self, message):
            await self._dispatch(message, "GROUP_AT_MESSAGE_CREATE")

        async def on_group_message_create(self, message):
            await self._dispatch(message, "GROUP_MESSAGE_CREATE")

        async def on_c2c_message_create(self, message):
            await self._dispatch(message, "C2C_MESSAGE_CREATE")

    # 注意：botpy 的 Intents 不是标准 enum.Flag，不能用 `a | b` 组合，
    # 必须用构造参数（实测 `Intents.public_messages | Intents.direct_message` 会 TypeError）
    intents = Intents(public_messages=True, direct_message=True)
    kwargs = {"is_sandbox": sandbox}
    if debug:
        kwargs["log_level"] = logging.DEBUG
    handler = QQHandler(api_base, reply_text=reply_text)
    return BanwutongBot(intents=intents, handler=handler, dry_run=dry_run, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="启动 QQ 机器人，把消息和图片/文件转给班务通"
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印事件，不写入后端也不回复")
    parser.add_argument(
        "--sandbox",
        action="store_true",
        default=os.environ.get("QQBOT_SANDBOX", "").lower() in ("1", "true", "yes"),
        help="连沙箱环境（机器人未上线、私聊收不到消息时试试）",
    )
    parser.add_argument("--debug", action="store_true", help="打印 botpy 调试日志，用来看平台有没有推事件")
    parser.add_argument("--api", default=os.environ.get("BANWUTONG_API", "http://127.0.0.1:8765"))
    parser.add_argument(
        "--reply-text",
        choices=("created", "always", "never"),
        default=os.environ.get("QQBOT_REPLY_TEXT", "created"),
        help="文字通知怎么回：created=只在新建事项时回，always=每次都回，never=不回",
    )
    args = parser.parse_args()

    appid = os.environ.get("QQBOT_APPID", "").strip()
    secret = os.environ.get("QQBOT_SECRET", "").strip()
    if not appid or not secret:
        raise SystemExit(
            "缺少 QQBOT_APPID / QQBOT_SECRET。\n"
            "到 QQ 开放平台控制台创建机器人后，把这两个值写进项目根目录的 .env（不要提交到仓库）。"
        )

    _install_full_group_message_support()
    bot = build_bot(
        args.api.rstrip("/"),
        args.dry_run,
        sandbox=args.sandbox,
        debug=args.debug,
        reply_text=args.reply_text,
    )

    print(
        f"连接 QQ 机器人 AppID={appid[:4]}****，后端={args.api}，"
        f"dry_run={args.dry_run}，sandbox={args.sandbox}，reply_text={args.reply_text}",
        flush=True,
    )
    bot.run(appid=appid, secret=secret)


if __name__ == "__main__":
    main()
