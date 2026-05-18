from __future__ import annotations
"""工具注册表测试。"""
import asyncio
from src.SmallShrimp.tools.registry import ToolRegistry
from src.SmallShrimp.tools.base import Tool, ToolResult


class MockTool(Tool):
    """测试用模拟工具。"""
    def __init__(self, name: str, description: str):
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, content=f"Executed {self._name}", error=None)


class EchoTool(Tool):
    """回显工具。"""
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes the input back"

    def get_parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message to echo"},
            },
            "required": ["message"],
        }

    async def execute(self, message: str) -> ToolResult:
        return ToolResult(success=True, content=f"Echo: {message}", error=None)


def test_tool_registry_init():
    """测试初始化。"""
    registry = ToolRegistry()
    assert len(registry._tools) == 0


def test_tool_registry_register():
    """测试注册工具。"""
    registry = ToolRegistry()
    tool = MockTool("test-tool", "A test tool")

    registry.register(tool)

    assert "test-tool" in registry._tools
    assert registry.get("test-tool") == tool


def test_tool_registry_get():
    """测试获取工具。"""
    registry = ToolRegistry()
    tool = MockTool("get-test", "Get test")
    registry.register(tool)

    retrieved = registry.get("get-test")
    assert retrieved is not None
    assert retrieved.name == "get-test"

    not_found = registry.get("nonexistent")
    assert not_found is None


def test_tool_registry_get_all():
    """测试获取所有工具。"""
    registry = ToolRegistry()
    registry.register(MockTool("tool1", "Tool 1"))
    registry.register(MockTool("tool2", "Tool 2"))

    all_tools = registry.get_all()
    assert len(all_tools) == 2


def test_tool_registry_get_schemas():
    """测试获取工具 schema。"""
    registry = ToolRegistry()
    echo = EchoTool()
    registry.register(echo)

    schemas = registry.get_schemas()
    assert len(schemas) == 1

    schema = schemas[0]
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "echo"
    assert schema["function"]["description"] == "Echoes the input back"


def test_tool_registry_execute_tool():
    """测试执行工具。"""
    registry = ToolRegistry()
    registry.register(EchoTool())

    result = asyncio.run(registry.execute_tool("echo", message="Hello"))
    assert "Echo: Hello" in result


def test_tool_registry_execute_not_found():
    """测试执行不存在的工具。"""
    registry = ToolRegistry()

    result = asyncio.run(registry.execute_tool("nonexistent"))
    assert "not found" in result


def test_tool_registry_multiple_tools():
    """测试注册多个工具。"""
    registry = ToolRegistry()
    registry.register(MockTool("multi1", "Multi 1"))
    registry.register(MockTool("multi2", "Multi 2"))
    registry.register(MockTool("multi3", "Multi 3"))

    assert len(registry.get_all()) == 3

    # 执行其中一个
    result = asyncio.run(registry.execute_tool("multi2"))
    assert "multi2" in result


if __name__ == "__main__":
    test_tool_registry_init()
    test_tool_registry_register()
    test_tool_registry_get()
    test_tool_registry_get_all()
    test_tool_registry_get_schemas()
    test_tool_registry_execute_tool()
    test_tool_registry_execute_not_found()
    test_tool_registry_multiple_tools()
    print("\nAll test_tool_registry tests passed!")