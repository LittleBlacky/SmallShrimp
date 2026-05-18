from __future__ import annotations
"""Channels 模块 - 多平台消息接入。"""
from .base import Channel
from .telegram_channel import TelegramChannel, TelegramEventSource
from .discord_channel import DiscordChannel, DiscordEventSource

__all__ = [
    "Channel",
    "TelegramChannel",
    "TelegramEventSource",
    "DiscordChannel",
    "DiscordEventSource",
]


def create_channels_from_config(config) -> list[Channel]:
    """从配置创建所有已启用的 Channel 实例。"""
    channels: list[Channel] = []

    channel_config = config.get_channel_config()

    if channel_config.telegram and channel_config.telegram.enabled:
        channels.append(TelegramChannel(channel_config.telegram))

    if channel_config.discord and channel_config.discord.enabled:
        channels.append(DiscordChannel(channel_config.discord))

    return channels