from __future__ import annotations
"""Delivery target — 指定消息投递目的地的统一模型。"""
from dataclasses import dataclass, field


@dataclass(slots=True)
class DeliveryTarget:
    """消息投递目标。

    Agent 通过此结构指定消息应该送到哪个平台的哪个目标。

    Attributes:
        platform: 平台标识，如 "telegram" / "discord" / "wecom" / "wecom_app" / "cli"
        target_type: 目标类型，如 "user" / "group" / "channel"
        target_id: 平台内的目标 ID（用户 ID、群 ID、频道 ID 等）
        display_name: 可读的名称（仅用于 LLM 展示）
    """
    platform: str
    target_type: str = "user"
    target_id: str = ""
    display_name: str = ""

    def describe(self) -> str:
        return f"{self.platform}:{self.target_type}:{self.target_id}"

    @classmethod
    def from_source_platform(cls, platform_name: str) -> "DeliveryTarget":
        """从 platform_name 构造一个指向该平台默认用户的 DeliveryTarget。"""
        return cls(platform=platform_name, target_type="user", target_id="default")
