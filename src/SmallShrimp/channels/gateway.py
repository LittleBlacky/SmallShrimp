from __future__ import annotations
"""Gateway manager — 集中管理所有 Channel，支持按 DeliveryTarget 分发。"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .target import DeliveryTarget

if TYPE_CHECKING:
    from .base import Channel

logger = logging.getLogger(__name__)


@dataclass
class GatewayStats:
    """Gateway 运行时统计。"""
    sent: int = 0
    failed: int = 0
    last_error: str = ""


class GatewayManager:
    """集中管理所有 Channel，提供跨平台消息投递。

    职责：
      - 注册所有 Channel
      - 按 DeliveryTarget.platform 路由到对应 Channel
      - broadcast() 广播到所有平台
      - 提供可用平台列表（供 LLM 工具参考）
    """

    def __init__(self):
        self._channels: dict[str, "Channel"] = {}
        self._stats: dict[str, GatewayStats] = {}

    def register(self, channel: "Channel") -> None:
        """注册一个 Channel。"""
        name = channel.platform_name
        self._channels[name] = channel
        self._stats.setdefault(name, GatewayStats())
        logger.info(f"Gateway 已注册平台: {name}")

    @property
    def platforms(self) -> list[str]:
        """返回所有已注册平台名称。"""
        return list(self._channels.keys())

    def get_channel(self, platform: str) -> "Channel | None":
        """获取指定平台的 Channel。"""
        return self._channels.get(platform)

    # ── 投递接口 ────────────────────────────────────────

    async def send(self, target: DeliveryTarget, content: str) -> bool:
        """投递消息到指定目标。成功返回 True。"""
        channel = self._channels.get(target.platform)
        if not channel:
            logger.warning(f"未知平台: {target.platform}，可用: {self.platforms}")
            self._stats.setdefault(target.platform, GatewayStats()).failed += 1
            self._stats[target.platform].last_error = f"未知平台"
            return False

        try:
            # 从 target 构造一个合适的 EventSource 占位
            from ..core.events.events import AgentEventSource
            source = AgentEventSource(agent_id="system")
            await channel.reply(content, source)
            self._stats[target.platform].sent += 1
            return True
        except Exception as e:
            logger.error(f"投递到 {target.platform} 失败: {e}")
            self._stats[target.platform].failed += 1
            self._stats[target.platform].last_error = str(e)
            return False

    async def broadcast(self, content: str) -> dict[str, bool]:
        """广播消息到所有已注册平台。返回 {platform: success}。"""
        results: dict[str, bool] = {}
        for platform in self._channels:
            target = DeliveryTarget(platform=platform, target_type="user", target_id="broadcast")
            results[platform] = await self.send(target, content)
        return results

    # ── 生命周期 ────────────────────────────────────────

    async def start_all(self) -> None:
        """所有 Channel 开始监听（需在 ChannelWorker 中启动 run）。"""
        count = len(self._channels)
        logger.info(f"GatewayManager 就绪，管理 {count} 个平台: {list(self._channels)}")

    async def stop_all(self) -> None:
        """优雅停止所有 Channel。"""
        for platform, channel in self._channels.items():
            try:
                await channel.stop()
            except Exception as e:
                logger.warning(f"停止 {platform} Channel 时出错: {e}")

    # ── 统计 ────────────────────────────────────────────

    def get_stats(self) -> dict[str, dict]:
        """获取各平台投递统计。"""
        return {
            platform: {
                "sent": stats.sent,
                "failed": stats.failed,
                "last_error": stats.last_error,
            }
            for platform, stats in self._stats.items()
        }
