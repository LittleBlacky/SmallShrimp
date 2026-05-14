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
    """工具基类。"""
    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称。"""
        ...
        
    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述（告诉 LLM 这个工具做什么）。"""
        ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """执行工具。"""
        ...

    def get_schema(self) -> dict:
        """获取工具的 JSON Schema（供 LLM 使用）。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters(),
            },
        }

    def get_parameters(self) -> dict:
        """获取参数 schema（子类可重写）。"""
        return {"type": "object", "properties": {}}