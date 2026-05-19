from __future__ import annotations
"""Telegram 频道实现。"""
import asyncio
from dataclasses import dataclass
from typing import Callable, Awaitable

from ..core.events import EventSource
from ..utils.config import TelegramConfig
from .base import Channel


@dataclass
class TelegramEventSource(EventSource):
    """Telegram 来源的事件。"""
    _namespace = "platform-telegram"
    user_id: str
    chat_id: str

    def __str__(self) -> str:
        return f"platform-telegram:{self.user_id}:{self.chat_id}"

    @classmethod
    def from_string(cls, s: str) -> "TelegramEventSource":
        _, user_id, chat_id = s.split(":")
        return cls(user_id=user_id, chat_id=chat_id)

    @property
    def platform_name(self) -> str:
        return "telegram"


class TelegramChannel(Channel[TelegramEventSource]):
    """Telegram 平台实现。"""

    platform_name = "telegram"
    max_message_length = 4096

    def __init__(self, config: TelegramConfig):
        self.config = config
        self._app = None
        self._running_task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._on_message: Callable | None = None

    def is_allowed(self, source: TelegramEventSource) -> bool:
        """检查发送者是否在白名单中。"""
        if not self.config.allowed_user_ids:
            return True
        return source.user_id in self.config.allowed_user_ids

    async def run(self, on_message: Callable[[str, TelegramEventSource], Awaitable[None]]) -> None:
        """启动 Telegram 频道。"""
        self._on_message = on_message
        self._stop_event = asyncio.Event()

        try:
            from telegram import Update
            from telegram.ext import Application, MessageHandler, filters, ContextTypes
        except ImportError:
            raise ImportError("python-telegram-bot 未安装，请运行: pip install python-telegram-bot")

        self._app = Application.builder().token(self.config.bot_token).build()

        async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if update.message and update.message.text and update.effective_chat and update.message.from_user:
                user_id = str(update.message.from_user.id)
                chat_id = str(update.effective_chat.id)
                message = update.message.text

                source = TelegramEventSource(user_id=user_id, chat_id=chat_id)

                try:
                    if self._on_message:
                        await self._on_message(message, source)
                except Exception as e:
                    self.logger.error(f"消息回调出错: {e}")

        self._app.add_handler(MessageHandler(filters.TEXT, handle_message))

        await self._app.initialize()
        await self._app.start()

        if self._app.updater:
            await self._app.updater.start_polling()

        async def run_until_stopped():
            while self._app and self._app.updater:
                if self._app.updater.running:
                    if self._stop_event and self._stop_event.is_set():
                        return
                    await asyncio.sleep(1)
                else:
                    return

        self._running_task = asyncio.create_task(run_until_stopped())
        await self._running_task

    async def reply(self, content: str, source: TelegramEventSource) -> None:
        """回复消息。"""
        if not self._app:
            raise RuntimeError("TelegramChannel 未启动")
        await self._app.bot.send_message(chat_id=int(source.chat_id), text=content)

    async def stop(self) -> None:
        """停止 Telegram bot。"""
        if self._app is None:
            return

        if self._stop_event:
            self._stop_event.set()

        if self._app.updater and self._app.updater.running:
            await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()

        if self._running_task and not self._running_task.done():
            try:
                await asyncio.wait_for(self._running_task, timeout=2.0)
            except asyncio.TimeoutError:
                pass

        self._app = None
        self._running_task = None
        self._stop_event = None
