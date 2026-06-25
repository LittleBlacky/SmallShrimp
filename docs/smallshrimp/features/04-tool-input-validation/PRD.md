# 工具入参校验 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 涉及层: Tools

---

## 1. 产品概述

### 1.1 产品定位

在 `tools/registry.py` 层面引入统一的入参校验层，让每个工具声明 Pydantic 输入模型或 JSON Schema，在调用链路的 `ToolRegistry.execute_tool()` 处做类型校验、缺省补全和错误格式化，减少因 LLM 传参异常导致的工具调用失败。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| 每个工具内部自行校验 `**kwargs`，LLM 传错参数类型或遗漏时只得到运行时异常 | 统一校验层，LLM 参数在进入工具体之前即可被拒绝，并返回结构化的错误信息 |
| 工具 Schema 由 `@tool` 装饰器生成，与真实函数签名可能不一致 | Schema 自动从 Pydantic 模型推导，签名与 Schema 完全同步 |
| LLM 收到 "Error: ..." 字符串时难以定位问题 | 错误信息包含期望的参数类型、名称和实际收到的值 |
| 无参数间交叉校验能力 | Pydantic model_validator 支持字段间依赖关系校验 |

### 1.3 目标用户

- **工具开发者**：声明 Pydantic 模型后自动获得校验、Schema 生成、错误格式化
- **LLM Agent**：收到结构化的错误反馈后可以自行修正参数重试
- **平台维护者**：通过统一的参数校验日志排查 LLM 幻觉导致的工具调用问题

---

## 2. 功能范围

### 2.1 MVP（P0 — 必须实现）

| 模块 | 功能 | 说明 |
|------|------|------|
| **Tool** | 可选 `input_model` 属性 | 工具可关联一个 Pydantic BaseModel，声明期望的参数结构 |
| **ToolRegistry** | `execute_tool` 校验层 | 调用工具前用 `input_model.model_validate(kwargs)` 做校验 |
| **ToolRegistry** | 错误格式化 | 校验失败时返回标准化错误：`ValidationError: field 'path': Field required (got: {'path': None})` |
| **Schema 生成** | 从 input_model 推导 | `tool.get_schema()` 从 Pydantic model 的 JSON Schema 生成 OpenAI 兼容的 `parameters` |

### 2.2 V1（P1 — 体验完善）

| 模块 | 功能 |
|------|------|
| **校验层** | 支持严格模式（禁止未知字段）和宽松模式（忽略未知字段） |
| **校验层** | 支持参数默认值自动填充（Pydantic field default） |
| **Schema 生成** | 从 model 的 `description` 和 `field_description` 自动注入 schema 描述 |

### 2.3 V2（P2 — 高级功能）

| 模块 | 功能 |
|------|------|
| **校验层** | 参数交叉校验（`model_validator`），如 `mode="create"` 时 `path` 不能已存在 |
| **校验层** | 校验结果缓存（同 session 内同一套参数不重复校验） |

---

## 3. 技术架构

```
                    LLM 调用工具
                         │
                         ▼
                 ┌───────────────────┐
                 │  ToolRegistry     │
                 │  execute_tool()   │
                 └───────┬───────────┘
                         │
                         ▼
             ┌───────────────────────┐
             │  input_model 存在？    │
             └──────┬──────────┬─────┘
                   否│        │是
                    ▼        ▼
              直接调用     model_validate(args)
                    │        │
                    │    ┌───┴──── Valid ──► 调用
                    │    │
                    │    └─── Invalid ──► 格式化错误返回
                    │
                    └───► 向后兼容
```

### 3.1 核心改动：Tool 基类

```python
# tools/base.py
from pydantic import BaseModel

class Tool:
    """工具基类。"""

    def __init__(self, name, description, input_model=None, **kwargs):
        self.name = name
        self.description = description
        self.input_model: type[BaseModel] | None = input_model
        # ...

    def get_schema(self) -> dict:
        """获取 OpenAI 兼容的 tool schema。"""
        schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
        if self.input_model:
            model_schema = self.input_model.model_json_schema()
            schema["parameters"] = model_schema
        return schema
```

### 3.2 核心改动：ToolRegistry.execute_tool

```python
# tools/registry.py
class ToolRegistry:
    async def execute_tool(self, name: str, **kwargs) -> str:
        tool = self.get(name)
        if not tool:
            return f"Error: Tool '{name}' not found"

        # 统一校验层
        if tool.input_model is not None:
            try:
                validated = tool.input_model.model_validate(kwargs)
                kwargs = validated.model_dump()
            except ValidationError as e:
                # 格式化校验错误
                errors = []
                for err in e.errors():
                    loc = ".".join(str(l) for l in err["loc"])
                    errors.append(f"  - {loc}: {err['msg']} (got: {err.get('input', '???')})")
                return (
                    f"ValidationError for tool '{name}':\n"
                    + "\n".join(errors)
                    + f"\n\nExpected parameters: {tool.get_schema()['parameters']}"
                )

        # 执行原有的工具调用
        result = await tool.call(**kwargs)
        if result.error:
            return f"Error: {result.error}"
        return result.content
```

### 3.3 工具声明示例

```python
# tools/builtin_tools.py
from pydantic import BaseModel, Field

class ReadInput(BaseModel):
    path: str = Field(description="File path to read")
    offset: int = Field(default=0, ge=0, description="Line offset")
    limit: int = Field(default=500, ge=0, description="Max lines, 0 for full file")

@tool(
    name="read",
    description="Read a file. offset/limit in lines.",
    input_model=ReadInput,
)
async def read(path: str, offset: int = 0, limit: int = 500) -> str:
    # 入参已校验完毕，直接使用
    ...
```

---

## 4. 迁移路径

将现有工具逐步接入 `input_model`：

| 工具 | 优先级 | 说明 |
|------|--------|------|
| `read` | P0 | 路径、offset、limit 都需要类型校验 |
| `write` | P0 | path 必选、content 必选、模式校验 |
| `glob` | P0 | pattern 必选，支持可选 path |
| `grep` | P0 | 新参数多的工具直接从设计阶段接入 |
| `shell_tool` | P1 | command 必选，timeout 校验 |
| `web_tools` | P1 | URL 格式校验 |
| `skill_tool` | P2 | 可选延迟接入 |

---

## 5. 测试要点

| 场景 | 说明 |
|------|------|
| 有 input_model 的工具 | 传入错误类型 → `ValidationError` 格式化返回，不抛异常 |
| 无 input_model 的工具 | 向后兼容，走旧路径 |
| 缺少必选参数 | 返回包含缺失字段名的错误 |
| 多余字段 | 宽松模式忽略 / 严格模式拒绝 |
| 参数默认值 | 未传的参数自动填充默认值 |
| Schema 一致性 | `get_schema()` 返回的 `properties` 与 `input_model` 字段一致 |

---

## 6. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | Tool 基类 + `input_model` 属性 + Registry 校验层 + 错误格式化 + Schema 推导 | 2d |
| P0+ | `read`/`write`/`glob`/`grep` 接入 Pydantic 模型 | 1d |
| P1 | 严格/宽松模式 + 剩余工具接入 | 1d |
| P2 | 交叉校验 + 校验缓存 | 1d |

---

## 7. 风险 & 缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Pydantic 对大项目的 import 速度影响 | 工具加载变慢 | 仅在有 `input_model` 的工具上 import，惰性加载 |
| 现有工具 schema 与 Pydantic 推导 schema 不一致 | LLM 生成错误的参数格式 | 先对比差异，逐工具迁移，保留旧 schema 兼容期 |
| 工具函数签名与 input_model 重复维护 | 双源不一致 | 从 input_model 推导签名（如需要），或在工具体用 `**kwargs` + validated model |

---

## 8. 附录

### 8.1 参考产品

- **FastAPI / Pydantic**：`model_validate()` + `model_json_schema()` 是成熟的模式，本方案直接复用
- **Anthropic Tool Use**：工具 schema 支持 `input_schema` 独立字段

### 8.2 变更文件

| 文件 | 变更类型 |
|------|----------|
| `src/SmallShrimp/tools/base.py` | 修改 — Tool 类增加 `input_model` 属性 |
| `src/SmallShrimp/tools/registry.py` | 修改 — `execute_tool` 增加校验层 |
| `src/SmallShrimp/tools/decorators.py` | 修改 — `@tool` 支持 `input_model` 参数 |
| `src/SmallShrimp/tools/builtin_tools.py` | 修改 — 接入 Pydantic 模型 |

### 8.3 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始草案 |
