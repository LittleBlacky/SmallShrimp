"""工具注册表。"""
from .base import Tool
import importlib

class ToolRegistry:
    """管理所有可用工具。"""
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """根据名称获取工具。"""
        return self._tools.get(name)

    def get_all(self) -> list[Tool]:
        """获取所有工具。"""
        return list(self._tools.values())

    def get_schemas(self) -> list[dict]:
        """获取所有工具的 schema（供 LLM 使用）。"""
        return [tool.get_schema() for tool in self._tools.values()]
        
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