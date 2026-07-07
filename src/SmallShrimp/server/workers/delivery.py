from __future__ import annotations
"""Delivery Worker - 订阅 OutboundEvent 并通过对应 Channel 投递。"""
import asyncio
import logging
import random
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from ...core.events.events import OutboundEvent
from .base import SubscriberWorker

if TYPE_CHECKING:
    from ..context import Context
    from ...channels.base import Channel
    from ...channels.target import DeliveryTarget

logger = logging.getLogger(__name__)

# 重试配置
BACKOFF_MS = [5000, 25000, 120000, 600000]  # 5s, 25s, 2min, 10min
MAX_RETRIES = 5


def compute_backoff_ms(retry_count: int) -> int:
    """计算带 jitter 的退避时间。"""
    if retry_count <= 0:
        return 0
    idx = min(retry_count - 1, len(BACKOFF_MS) - 1)
    base = BACKOFF_MS[idx]
    jitter = random.randint(-base // 5, base // 5)
    return max(0, base + jitter)


def chunk_message(content: str, limit: int) -> list[str]:
    """按段落边界分割消息，同时遵守限制。"""
    if len(content) <= limit:
        return [content]

    chunks = []
    paragraphs = content.split("\n\n")
    current = ""

    for para in paragraphs:
        if current:
            potential = current + "\n\n" + para
        else:
            potential = para

        if len(potential) <= limit:
            current = potential
        else:
            if current:
                chunks.append(current)

            if len(para) > limit:
                for i in range(0, len(para), limit):
                    chunks.append(para[i : i + limit])
                current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    return chunks


class DeliveryWorker(SubscriberWorker):
    """将 OutboundEvent 投递到对应平台的 Worker。

    投递策略（按优先级）：
      1. event.delivery_target 指定平台 → 投递到指定平台
      2. event.source.platform_name 从来源推断 → 回复来源平台（旧行为）
      3. 以上都不满足 → 跳过投递
    """

    def __init__(self, context: "Context"):
        super().__init__(context)
        self.context.eventbus.subscribe(OutboundEvent, self.handle_event)
        self.logger.info("DeliveryWorker 已订阅 OutboundEvent 事件")

    @lru_cache(maxsize=10)
    def _get_channel(self, platform: str) -> "Channel | None":
        """获取指定平台的 Channel。"""
        channels = getattr(self.context, "channels", [])
        for channel in channels:
            if channel.platform_name == platform:
                return channel
        return None

    def _get_gateway(self) -> "Any | None":
        """获取 GatewayManager（如果可用）。"""
        return getattr(self.context, "gateway_manager", None)

    async def _deliver_with_retry(
        self, chunks: list[str], source, channel: "Channel"
    ) -> bool:
        """使用重试逻辑投递所有分块。成功返回 True。"""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                for chunk in chunks:
                    await channel.reply(chunk, source)
                return True
            except Exception as e:
                if attempt < MAX_RETRIES:
                    backoff_ms = compute_backoff_ms(attempt)
                    self.logger.warning(
                        f"投递失败 (尝试 {attempt}/{MAX_RETRIES})，"
                        f"{backoff_ms}ms 后重试: {e}"
                    )
                    await asyncio.sleep(backoff_ms / 1000)
                else:
                    self.logger.error(f"投递失败，已达最大重试次数: {e}")
                    return False
        return False

    async def _deliver_to_target(self, target: "DeliveryTarget", content: str, source) -> bool:
        """通过 GatewayManager 投递到指定 DeliveryTarget。"""
        gateway = self._get_gateway()
        if gateway:
            return await gateway.send(target, content)

        # 回退：通过 source 找 Channel
        channel = self._get_channel(target.platform)
        if not channel:
            self.logger.warning(f"未找到平台 {target.platform} 的 Channel")
            return False
        limit = getattr(channel, "max_message_length", 2**31)
        chunks = chunk_message(content, limit)
        return await self._deliver_with_retry(chunks, source, channel)

    async def handle_event(self, event: OutboundEvent) -> None:
        """处理 OutboundEvent 投递。"""
        try:
            source = event.source

            # 优先级 1: delivery_target 指定平台
            if event.delivery_target is not None:
                success = await self._deliver_to_target(
                    event.delivery_target, event.content, source
                )
                if success:
                    self.logger.info(
                        f"已投递消息到 {event.delivery_target.platform}，会话 {event.session_id}"
                    )
                else:
                    self.logger.error(f"投递到 {event.delivery_target.platform} 失败")
                self.context.eventbus.ack(event)
                return

            # 优先级 2: 从 event source 推断平台
            if not source.platform_name:
                self.logger.warning(
                    f"会话 {event.session_id} 无平台来源且无 delivery_target，跳过投递"
                )
                self.context.eventbus.ack(event)
                return

            channel = self._get_channel(source.platform_name)
            if not channel:
                self.logger.warning(
                    f"未找到平台 {source.platform_name} 的 Channel"
                )
                self.context.eventbus.ack(event)
                return

            limit = getattr(channel, "max_message_length", 2**31)
            chunks = chunk_message(event.content, limit)

            success = await self._deliver_with_retry(chunks, source, channel)
            if not success:
                self.logger.error(f"丢弃会话 {event.session_id} 的消息")

            self.context.eventbus.ack(event)
            self.logger.info(
                f"已投递消息到 {source.platform_name}，会话 {event.session_id}"
            )

        except Exception as e:
            self.logger.error(f"投递消息失败: {e}")
            try:
                self.context.eventbus.ack(event)
            except Exception:
                pass
