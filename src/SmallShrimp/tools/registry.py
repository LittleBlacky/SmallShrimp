"""工具注册表。"""
from __future__ import annotations
from .base import Tool, ToolPermission
import importlib


class ToolRegistry:
    """管理所有可用工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._activated: set[str] = set()  # deferred 工具激活集合

    def register(self, tool: Tool) -> None:
        """注册一个工具。DENY 工具静默丢弃。"""
        if tool.permission == ToolPermission.DENY:
            return
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """根据名称获取工具。"""
        return self._tools.get(name)

    def get_all(self) -> list[Tool]:
        """获取所有工具。"""
        return list(self._tools.values())

    def get_schemas(self, *, active_only: bool = False) -> list[dict]:
        """获取工具 schema（供 LLM 使用）。

        active_only=True 时只返回非 deferred 工具 + 已激活的 deferred 工具。
        """
        tools = self._tools.values()
        if active_only:
            tools = [
                t for t in tools
                if not t.deferred or t.name in self._activated
            ]
        return [tool.get_schema() for tool in tools]

    def activate_deferred(self, name: str) -> Tool | None:
        """激活一个 deferred 工具。返回该工具或 None。"""
        tool = self._tools.get(name)
        if tool and tool.deferred:
            self._activated.add(name)
        return tool

    def get_deferred_names(self) -> list[str]:
        """返回所有未激活的 deferred 工具名称。"""
        return [
            t.name for t in self._tools.values()
            if t.deferred and t.name not in self._activated
        ]

    def get_active_names(self) -> list[str]:
        """返回所有当前可用的工具名称。"""
        return [
            t.name for t in self._tools.values()
            if not t.deferred or t.name in self._activated
        ]

    def load_from_module(self, module_name: str) -> None:
        """从模块自动发现并注册所有 @tool 装饰的工具。"""
        module = importlib.import_module(module_name)

        for name, obj in vars(module).items():
            if name.startswith("_"):
                continue
            if isinstance(obj, Tool):
                self.register(obj)

    async def execute_tool(self, name: str, **kwargs) -> str:
        """执行工具并返回结果字符串。"""
        tool = self.get(name)
        if not tool:
            return f"Tool '{name}' not found"
        result = await tool.call(**kwargs)
        if result.error:
            return f"Error: {result.error}"
        return result.content

    def search(self, query: str) -> list[Tool]:
        """按名称/描述搜索工具（用于 tool_search）。"""
        query_lower = query.lower()
        results: list[tuple[int, Tool]] = []
        for tool in self._tools.values():
            name_lower = tool.name.lower()
            desc_lower = tool.description.lower()
            if query_lower == name_lower:
                results.append((20, tool))
            elif query_lower in name_lower:
                results.append((12, tool))
            elif query_lower in desc_lower:
                results.append((5, tool))
        results.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in results]
