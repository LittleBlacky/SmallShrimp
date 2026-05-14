"""工具装饰器。"""
from functools import wraps
from inspect import signature, Parameter
from typing import Callable, Any
from tools.base import Tool, ToolResult

def tool(name: str, description: str):
    """
    装饰器：把一个 async 函数变成 Tool。
    用法：
        @tool(name="read", description="读取文件")
        async def read(path: str) -> str:
            return Path(path).read_text()
    """
    def decorator(fn: Callable) -> Tool:
        @wraps(fn)
        async def wrapper(**kwargs: Any) -> ToolResult:
            try:
                result = fn(**kwargs)
                if hasattr(result, "__await__"):
                    result = await result
                return ToolResult(success=True, content=str(result), error=None)
            except Exception as e:
                return ToolResult(success=False, content="", error=str(e))

        class FunctionTool(Tool):
            _name = name
            _description = description
            _fn = fn
            _params = _extract_params(fn)
            @property
            def name(self) -> str:
                return self._name
            @property
            def description(self) -> str:
                return self._description
            def get_parameters(self) -> dict:
                return self._params
            async def execute(self, **kwargs: Any) -> ToolResult:
                return await wrapper(**kwargs)
            async def call(self, **kwargs: Any) -> ToolResult:
                return await wrapper(**kwargs)
        return FunctionTool()
    return decorator

def _extract_params(fn: Callable) -> dict:
    """从函数签名提取 JSON Schema 参数。"""
    sig = signature(fn)
    properties = {}
    required = []
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        param_type = _python_type_to_json(param.annotation)
        properties[param_name] = {
            "type": param_type,
            "description": f"Parameter: {param_name}",
        }
        if param.default is Parameter.empty:
            required.append(param_name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }

def _python_type_to_json(py_type) -> str:
    """Python 类型映射到 JSON Schema 类型。"""
    type_map = {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
    }
    name = getattr(py_type, "__name__", str(py_type))
    return type_map.get(name, "string")