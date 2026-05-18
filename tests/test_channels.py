from __future__ import annotations
"""Channel 基类测试。"""
import pytest
from src.SmallShrimp.channels.base import Channel
from src.SmallShrimp.channels.telegram_channel import TelegramChannel, TelegramEventSource
from src.SmallShrimp.channels.discord_channel import DiscordChannel, DiscordEventSource
from src.SmallShrimp.utils.config import TelegramConfig, DiscordConfig


def test_channel_abstract():
    """测试 Channel 是抽象类。"""
    with pytest.raises(TypeError):
        Channel()


def test_telegram_event_source():
    """测试 TelegramEventSource。"""
    source = TelegramEventSource(user_id="123", chat_id="456")
    assert str(source) == "platform-telegram:123:456"
    assert source.platform_name == "telegram"
    assert source.is_platform


def test_telegram_event_source_from_string():
    """测试 TelegramEventSource 字符串解析。"""
    source = TelegramEventSource.from_string("platform-telegram:123:456")
    assert source.user_id == "123"
    assert source.chat_id == "456"


def test_discord_event_source():
    """测试 DiscordEventSource。"""
    source = DiscordEventSource(user_id="789", channel_id="101")
    assert str(source) == "platform-discord:789:101"
    assert source.platform_name == "discord"
    assert source.is_platform


def test_discord_event_source_from_string():
    """测试 DiscordEventSource 字符串解析。"""
    source = DiscordEventSource.from_string("platform-discord:789:101")
    assert source.user_id == "789"
    assert source.channel_id == "101"


def test_telegram_channel_creation():
    """测试创建 Telegram Channel。"""
    config = TelegramConfig(enabled=True, bot_token="test-token")
    channel = TelegramChannel(config)
    assert channel.platform_name == "telegram"


def test_telegram_channel_whitelist():
    """测试 Telegram 白名单功能。"""
    config = TelegramConfig(
        enabled=True,
        bot_token="test-token",
        allowed_user_ids=["123", "456"]
    )
    channel = TelegramChannel(config)
    source_allowed = TelegramEventSource(user_id="123", chat_id="789")
    source_denied = TelegramEventSource(user_id="999", chat_id="789")

    assert channel.is_allowed(source_allowed) is True
    assert channel.is_allowed(source_denied) is False


def test_discord_channel_creation():
    """测试创建 Discord Channel。"""
    config = DiscordConfig(enabled=True, bot_token="test-token")
    channel = DiscordChannel(config)
    assert channel.platform_name == "discord"


def test_discord_channel_whitelist():
    """测试 Discord 白名单功能。"""
    config = DiscordConfig(
        enabled=True,
        bot_token="test-token",
        allowed_user_ids=["123", "456"]
    )
    channel = DiscordChannel(config)
    source_allowed = DiscordEventSource(user_id="123", channel_id="789")
    source_denied = DiscordEventSource(user_id="999", channel_id="789")

    assert channel.is_allowed(source_allowed) is True
    assert channel.is_allowed(source_denied) is False


def test_event_source_from_string_registry():
    """测试 EventSource 字符串解析注册表。"""
    from src.SmallShrimp.core.events import EventSource

    # CLI
    cli = EventSource.from_string("platform-cli:cli-user")
    assert cli.platform_name == "cli"

    # Telegram
    tg = EventSource.from_string("platform-telegram:123:456")
    assert tg.platform_name == "telegram"


if __name__ == "__main__":
    test_channel_abstract()
    test_telegram_event_source()
    test_telegram_event_source_from_string()
    test_discord_event_source()
    test_discord_event_source_from_string()
    test_telegram_channel_creation()
    test_telegram_channel_whitelist()
    test_discord_channel_creation()
    test_discord_channel_whitelist()
    test_event_source_from_string_registry()
    print("\nAll channel tests passed!")