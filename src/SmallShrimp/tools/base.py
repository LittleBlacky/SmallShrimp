from __future__ import annotations
"""工具基类。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class ToolResult:
    """工具执行结果。"""
    success: bool
    content: str
    error: str | None = None

class Tool(ABC):
    """工具基类，包含基础校验。"""
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