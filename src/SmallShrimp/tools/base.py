from __future__ import annotations
"""工具基类。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ToolPermission(str, Enum):
    """三级工具权限。"""
    SAFE = "safe"        # 只读，立即执行
    CONFIRM = "confirm"  # 有副作用，需用户确认
    DENY = "deny"        # 禁止，注册时丢弃


@dataclass
class ToolResult:
    """工具执行结果。"""
    success: bool
    content: str
    error: str | None = None


class Tool(ABC):
    """工具基类，包含基础校验。"""

    # ── 子类可覆盖的元数据 ────────────────────────────────
    permission: ToolPermission = ToolPermission.SAFE
    deferred: bool = False       # True = 不默认发送 schema，需 tool_search 激活
    is_destructive: bool = False  # True = 不可逆操作

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        ...

    def is_action_read_only(self, arguments: dict[str, Any]) -> bool:
        """参数级权限判定。子类可覆盖以实现单工具内读写分离。

        例如 cron_manage(action='list') 为只读，cron_manage(action='create') 为写操作。
        默认：SAFE 权限的工具视为只读。
        """
        return self.permission == ToolPermission.SAFE

    def get_schema(self) -> dict:
        """获取工具的 JSON Schema。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters(),
            },
        }

    def get_parameters(self) -> dict:
        """子类重写以定义参数 schema。"""
        return {"type": "object", "properties": {}}

    async def call(self, **kwargs: Any) -> ToolResult:
        """带基础校验的工具调用。"""
        # 1. 检查未知参数
        param_schema = self.get_parameters()
        allowed = set(param_schema.get("properties", {}).keys())
        for key in kwargs:
            if key.startswith("_"):
                continue
            if key not in allowed:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Unknown parameter: {key}",
                )
        # 2. 检查必填参数
        required = set(param_schema.get("required", []))
        for key in required:
            if key not in kwargs:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Missing required parameter: {key}",
                )
        # 3. 执行 + 异常捕获
        try:
            return await self.execute(**kwargs)
        except Exception as e:
            return ToolResult(success=False, content="", error=str(e))
