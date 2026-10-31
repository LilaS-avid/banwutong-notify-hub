"""QQ 机器人连接层：连上 QQ，把收到的消息转给班务通后端。

和 `app/qq_adapter.py` 的分工：
  - 本文件负责 **连接**（鉴权、WebSocket、心跳、重连），要有 AppID/AppSecret；
  - `qq_adapter.py` 负责 **转换**（平台事件 → 后端消息），纯逻辑、无凭证。

运行前准备（AppID/AppSecret 在 QQ 开放平台控制台，个人主体即可创建）：

    # .env
    QQBOT_APPID=你的AppID
    QQBOT_SECRET=你的AppSecret
    BANWUTONG_API=http://127.0.0.1:8765

启动：

    pip install -r requirements-bot.txt
    python -m scripts.run_qq_bot

只想看收到的消息、不写库（排查用）：

    python -m scripts.run_qq_bot --dry-run

注意：botpy 1.2.1 本身没有 `GROUP_MESSAGE_CREATE`（群内全量消息）的解析器，
本文件在启动时补了一个，否则群里不 @ 机器人的通知会被当成未知事件丢掉。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# 先加载项目根目录的 .env，否则 QQBOT_APPID / QQBOT_SECRET 读不到
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


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


def build_bot(api_base: str, dry_run: bool, sandbox: bool = False, debug: bool = False):
    from botpy import Client, Intents

    from app.qq_adapter import event_from_message, to_message_in

    class BanwutongBot(Client):
        async def _forward(self, message, event_type: str) -> None:
            payload = to_message_in(event_from_message(message, event_type))
            if payload is None:
                return
            if dry_run:
                print(json.dumps(payload, ensure_ascii=False), flush=True)
                return
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(f"{api_base}/api/messages", json=payload)
                disposition = ""
                try:
                    disposition = response.json().get("disposition", "")
                except ValueError:
                    disposition = response.text[:100]
                print(f"[{event_type}] {payload['external_id']} -> {response.status_code} {disposition}", flush=True)
            except Exception as error:  # noqa: BLE001 - 转发失败不能让机器人掉线
                print(f"[{event_type}] 转发失败：{type(error).__name__}: {error}", file=sys.stderr)

        async def on_group_at_message_create(self, message):
            await self._forward(message, "GROUP_AT_MESSAGE_CREATE")

        async def on_group_message_create(self, message):
            await self._forward(message, "GROUP_MESSAGE_CREATE")

        async def on_c2c_message_create(self, message):
            await self._forward(message, "C2C_MESSAGE_CREATE")

    # 注意：botpy 的 Intents 不是标准 enum.Flag，不能用 `a | b` 组合，
    # 必须用构造参数（实测 `Intents.public_messages | Intents.direct_message` 会 TypeError）
    intents = Intents(public_messages=True, direct_message=True)
    kwargs = {"is_sandbox": sandbox}
    if debug:
        import logging

        kwargs["log_level"] = logging.DEBUG
    return BanwutongBot(intents=intents, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 QQ 机器人并把消息转发给班务通")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写入后端")
    parser.add_argument(
        "--sandbox",
        action="store_true",
        default=os.environ.get("QQBOT_SANDBOX", "").lower() in ("1", "true", "yes"),
        help="连沙箱环境（机器人未上线、私聊收不到消息时试试）",
    )
    parser.add_argument("--debug", action="store_true", help="打印 botpy 调试日志，用来看平台有没有推事件")
    parser.add_argument("--api", default=os.environ.get("BANWUTONG_API", "http://127.0.0.1:8765"))
    args = parser.parse_args()

    appid = os.environ.get("QQBOT_APPID", "").strip()
    secret = os.environ.get("QQBOT_SECRET", "").strip()
    if not appid or not secret:
        raise SystemExit(
            "缺少 QQBOT_APPID / QQBOT_SECRET。\n"
            "到 QQ 开放平台控制台创建机器人后，把这两个值写进项目根目录的 .env（不要提交到仓库）。"
        )

    _install_full_group_message_support()
    bot = build_bot(args.api.rstrip("/"), args.dry_run, sandbox=args.sandbox, debug=args.debug)

    print(f"连接 QQ 机器人 AppID={appid[:4]}****，后端={args.api}，dry_run={args.dry_run}，sandbox={args.sandbox}")
    bot.run(appid=appid, secret=secret)


if __name__ == "__main__":
    main()
