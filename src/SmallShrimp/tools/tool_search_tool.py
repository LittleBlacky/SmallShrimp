"""tool_search — 按需发现并激活延迟加载的工具。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
from .base import Tool, ToolPermission, ToolResult

if TYPE_CHECKING:
    from .registry import ToolRegistry


class ToolSearchTool(Tool):
    name = "tool_search"
    description = (
        "搜索并激活未加载的工具。"
        "当需要使用不在当前工具列表中的能力时调用此工具。"
    )
    permission = ToolPermission.SAFE

    def __init__(self, registry: "ToolRegistry") -> None:
        self._registry = registry

    def get_parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词（工具名称或功能描述）",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        if not query:
            return ToolResult(success=False, content="", error="query is required")

        # 搜索所有工具（包括 deferred）
        matches = self._registry.search(query)

        # 激活 deferred 工具
        newly_activated = []
        for tool in matches:
            if tool.deferred and tool.name not in self._registry._activated:
                self._registry.activate_deferred(tool.name)
                newly_activated.append(tool)

        if not matches:
            return ToolResult(
                success=True,
                content=f"未找到与 '{query}' 相关的工具。",
            )

        lines = []
        if newly_activated:
            lines.append(f"已激活 {len(newly_activated)} 个工具：")
            for tool in newly_activated:
                lines.append(f"  - {tool.name}: {tool.description}")
            lines.append("")
            lines.append("这些工具现在可以在后续对话中使用。")

        # 列出匹配的工具
        lines.append(f"找到 {len(matches)} 个相关工具：")
        for tool in matches[:10]:
            status = "已激活" if tool.name in self._registry._activated else "可激活"
            lines.append(f"  - [{status}] {tool.name}: {tool.description}")

        return ToolResult(success=True, content="\n".join(lines))
