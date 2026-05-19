from __future__ import annotations
"""Channels 模块 - 多平台消息接入。"""
from .base import Channel
from .telegram_channel import TelegramChannel, TelegramEventSource
from .discord_channel import DiscordChannel, DiscordEventSource
from .wecom_channel import WeComChannel, WeComEventSource
from .wecom_app_channel import WeComAppChannel, WeComAppEventSource

__all__ = [
    "Channel",
    "TelegramChannel",
    "TelegramEventSource",
    "DiscordChannel",
    "DiscordEventSource",
    "WeComChannel",
    "WeComEventSource",
    "WeComAppChannel",
    "WeComAppEventSource",
]


def create_channels_from_config(config) -> list[Channel]:
    """从配置创建所有已启用的 Channel 实例。"""
    channels: list[Channel] = []

    channel_config = config.get_channel_config()

    if channel_config.telegram and channel_config.telegram.enabled:
        channels.append(TelegramChannel(channel_config.telegram))

    if channel_config.discord and channel_config.discord.enabled:
        channels.append(DiscordChannel(channel_config.discord))

    if channel_config.wecom and channel_config.wecom.enabled:
        channels.append(WeComChannel(channel_config.wecom.webhook_url))

    if channel_config.wecom_app and channel_config.wecom_app.enabled:
        from .wecom_app_channel import WeComAppChannel
        channels.append(WeComAppChannel(channel_config.wecom_app))

    return channels