from __future__ import annotations
"""工具装饰器测试。"""
import asyncio
from src.SmallShrimp.tools.decorators import tool, _extract_params, _python_type_to_json


# 测试辅助函数
async def async_add(a: int, b: int) -> int:
    """异步加法。"""
    return a + b


def sync_multiply(x: int, y: int) -> int:
    """同步乘法。"""
    return x * y


async def greet(name: str, greeting: str = "Hello") -> str:
    """问候函数。"""
    return f"{greeting}, {name}!"


def test_python_type_to_json():
    """测试 Python 类型到 JSON Schema 类型转换。"""
    assert _python_type_to_json(str) == "string"
    assert _python_type_to_json(int) == "integer"
    assert _python_type_to_json(float) == "number"
    assert _python_type_to_json(bool) == "boolean"
    assert _python_type_to_json(list) == "array"
    assert _python_type_to_json(dict) == "object"
    assert _python_type_to_json("unknown") == "string"


def test_extract_params():
    """测试从函数签名提取参数。"""
    params = _extract_params(greet)
    assert params["type"] == "object"
    assert "name" in params["properties"]
    assert "greeting" in params["properties"]
    assert params["properties"]["name"]["type"] == "string"
    assert "name" in params["required"]


def test_extract_params_with_defaults():
    """测试带默认值的参数。"""
    params = _extract_params(greet)
    # greeting 有默认值，不是必填
    assert "greeting" not in params["required"]


def test_extract_params_ignores_self():
    """测试忽略 self 参数。"""
    def method_with_self(self, arg1: str):
        pass

    params = _extract_params(method_with_self)
    assert "self" not in params["properties"]
    assert "arg1" in params["properties"]


def test_tool_decorator_sync():
    """测试装饰同步函数。"""
    @tool(name="sync_tool", description="A synchronous tool")
    def sync_tool(x: int, y: int) -> int:
        return x + y

    assert sync_tool.name == "sync_tool"
    assert sync_tool.description == "A synchronous tool"
    assert sync_tool.get_parameters()["properties"]["x"]["type"] == "integer"
    assert sync_tool.get_parameters()["properties"]["y"]["type"] == "integer"


def test_tool_decorator_async():
    """测试装饰异步函数。"""
    @tool(name="async_tool", description="An async tool")
    async def async_tool(a: str, b: str = "default") -> str:
        return f"{a}-{b}"

    assert async_tool.name == "async_tool"
    assert "a" in async_tool.get_parameters()["properties"]
    assert "b" in async_tool.get_parameters()["properties"]


def test_tool_decorator_execute():
    """测试工具执行。"""
    @tool(name="exec_test", description="Execution test")
    def exec_tool(x: int, y: int) -> int:
        return x * y + 10

    result = asyncio.run(exec_tool.execute(x=5, y=3))
    assert result.success is True
    assert result.content == "25"


def test_tool_decorator_execute_async():
    """测试异步工具执行。"""
    @tool(name="async_exec", description="Async execution test")
    async def async_exec(a: int, b: int) -> int:
        return a + b

    result = asyncio.run(async_exec.execute(a=10, b=20))
    assert result.success is True
    assert result.content == "30"


def test_tool_decorator_error_handling():
    """测试错误处理。"""
    @tool(name="error_tool", description="Error handling test")
    def error_tool(x: int) -> int:
        raise ValueError("Test error")

    result = asyncio.run(error_tool.execute(x=1))
    assert result.success is False
    assert "Test error" in result.error


def test_tool_decorator_call_validates():
    """测试 call 方法验证参数。"""
    @tool(name="validate_tool", description="Validation test")
    def validate_tool(required_arg: str, optional_arg: int = 0) -> str:
        return required_arg

    # 缺少必填参数
    result = asyncio.run(validate_tool.call())
    assert result.success is False
    assert "required_arg" in result.error

    # 提供必填参数
    result = asyncio.run(validate_tool.call(required_arg="test"))
    assert result.success is True


def test_tool_decorator_default_name():
    """测试默认工具名。"""
    @tool(description="Default name test")
    def my_custom_tool() -> str:
        return "custom"

    assert my_custom_tool.name == "my_custom_tool"


def test_tool_decorator_default_description():
    """测试默认描述（使用 docstring）。"""
    @tool(name="docstring_test")
    def docstring_tool() -> str:
        """This is the docstring description."""
        return "result"

    assert docstring_tool.description == "This is the docstring description."


if __name__ == "__main__":
    test_python_type_to_json()
    test_extract_params()
    test_extract_params_with_defaults()
    test_extract_params_ignores_self()
    test_tool_decorator_sync()
    test_tool_decorator_async()
    test_tool_decorator_execute()
    test_tool_decorator_execute_async()
    test_tool_decorator_error_handling()
    test_tool_decorator_call_validates()
    test_tool_decorator_default_name()
    test_tool_decorator_default_description()
    print("\nAll test_tools tests passed!")