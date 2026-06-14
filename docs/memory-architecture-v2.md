# SmallShrimp 记忆层架构设计 v2

> 最终更新: 2026-06-12

---

## 目录

1. [设计目标](#1-设计目标)
2. [核心原则](#2-核心原则)
3. [架构总览](#3-架构总览)
4. [MemoryProvider ABC — 最小契约](#4-memoryprovider-abc--最小契约)
5. [MemoryManager — 纯代理层](#5-memorymanager--纯代理层)
6. [PromptBlock — 分层注入](#6-promptblock--分层注入)
7. [工具注册 — @tool 自注册](#7-工具注册--tool-自注册)
8. [Factory — 配置驱动创建](#8-factory--配置驱动创建)
9. [内置 BuiltinProvider](#9-内置-builtinprovider)
10. [自定义 Provider 接入指南](#10-自定义-provider-接入指南)
11. [为什么这么设计](#11-为什么这么设计)
12. [效果与收益](#12-效果与收益)

---

## 1. 设计目标

### 要解决的问题

1. **记忆后端不可替换** — 旧版 `MemoryManager` 硬编码了 `BuiltinProvider`，换后端必须改框架代码
2. **层名耦合** — `Literal["profile","facts","projects","reflections","sessions"]` 写死在类型系统里，用户无法定义自己的层
3. **工具与存储耦合** — 记忆工具定义在 `tools/memory_tool.py`，换后端要同时改工具逻辑
4. **Prompt 注入硬编码** — `prompt_builder` 假设只有一段 "User Profile" 需要注入

### 设计目标

| # | 目标 | 衡量标准 |
|---|------|---------|
| 1 | **Provider 可替换** | 换记忆后端只需改一行 `config.yaml` |
| 2 | **层名可自定义** | 系统不假设任何层名，由 Provider 自己定义 |
| 3 | **工具自注册** | Provider 用 `@tool` 定义工具，系统自动注册 |
| 4 | **分层注入** | Provider 控制注入哪些内容、注入到哪个缓存层级 |
| 5 | **最小接口** | 用户实现自定义后端只需实现 4 个核心方法 |

---

## 2. 核心原则

### 2.1 面向接口而非实现

```
MemoryProvider (ABC) ← BuiltinProvider
                    ← MyCustomProvider
                    ← ThirdPartyProvider
```

`MemoryManager` 只依赖 `MemoryProvider` ABC，不知道也不关心具体的后端实现。

### 2.2 Provider 自描述

Provider 自己描述：

- **支持哪些工具**（`get_tools()` → `@tool` 装饰的函数）
- **要注入 prompt 什么内容**（`get_prompt_blocks()` → `PromptBlock` 列表）
- **用什么层名**（`store("contacts", ...)` 而不是 `store("profile", ...)`）

系统只负责编排，不负责假设。

### 2.3 最小契约，最大灵活

ABC 只有 4 个抽象方法（`store`/`search`/`list_all`/`get_tools`），其余都有默认空实现。用户只需要实现自己需要的功能。

### 2.4 向后兼容

旧 API（`system_prompt_block()`、路径构造 `MemoryManager(Path)`）保留默认委托，已有代码无需改动。

---

## 3. 架构总览

```
config.yaml
    │
    ▼
┌───────────────────────────────────────────────┐
│         create_memory_manager(config)          │  ← 工厂
│                                               │
│  ┌─ "builtin"     → BuiltinProvider           │
│  └─ "my.MyProv"   → importlib 动态加载        │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│              MemoryManager(provider)           │  ← 纯代理层
│                                               │
│  store()  /  recall()  /  list_all()          │
│  delete()  /  consolidate()                   │
│  get_prompt_blocks()  /  get_tools()          │
│  initialize()  /  prefetch()  /  sync_turn()  │
└──────┬──────────────────┬────────────────────┘
       │                  │
       ▼                  ▼
┌──────────────┐  ┌──────────────────┐
│  Agent/Tools  │  │  PromptBuilder   │
│              │  │                  │
│ provider     │  │ get_prompt_      │
│ .get_tools() │  │ blocks()         │
│ → 注册       │  │ → 按 cache_tier  │
│   到 Registry │  │   分层注入        │
└──────────────┘  └──────────────────┘
```

### 目录结构

```
src/SmallShrimp/core/memory/
├── __init__.py          # 导出 + create_memory_manager() 工厂
├── provider.py          # MemoryProvider ABC + PromptBlock 定义
├── memory_manager.py    # 纯代理层
└── builtin/             # 内置实现（可整体替换或删除）
    ├── __init__.py
    ├── provider.py      # BuiltinProvider
    ├── file_store.py    # MarkdownStore（文件真相源 + SQLite FTS5）
    ├── hybrid_search.py # FTS5 + sqlite-vec 混合检索 + MMR 重排序
    ├── common.py        # 通用工具
    └── store.py         # 旧 SQLiteBackend（待废弃）
```

---

## 4. MemoryProvider ABC — 最小契约

### 4.1 必须实现（4 个）

```python
class MemoryProvider(ABC):

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider 唯一标识，如 'builtin', 'my_mem'."""

    @abstractmethod
    def is_available(self) -> bool:
        """检查后端是否可用。"""

    @abstractmethod
    def store(self, layer: str, content: str, **kwargs) -> dict:
        """写入一条记忆。

        Args:
            layer: 层名（Provider 自己定义语义，如 "notes"/"contacts"）
            content: 记忆内容
        Returns:
            写入后的完整记录 dict（至少包含 id / content / layer）
        """

    @abstractmethod
    def search(self, query: str, layer: str | None = None, **kwargs) -> list[dict]:
        """检索记忆。"""

    @abstractmethod
    def list_all(self, layer: str | None = None, **kwargs) -> list[dict]:
        """列出所有记录。"""

    @abstractmethod
    def get_tools(self) -> list:
        """返回此 Provider 提供的 Tool 对象列表。

        每个 Tool 由 @tool 装饰器创建，系统自动注册到 ToolRegistry。
        """
```

### 4.2 有默认实现（无需覆盖）

```python
    def initialize(self, session_id: str) -> None: ...
    def shutdown(self) -> None: ...
    def close(self) -> None: ...
    def prefetch(self, query, session_id="") -> list[dict]: ...
    def sync_turn(self, ...) -> None: ...
    def delete(self, record_id) -> bool: ...
    def consolidate(self, **kwargs) -> int: ...
    def get_prompt_blocks(self) -> list[PromptBlock]: ...
    def system_prompt_block(self) -> str: ...
```

### 4.3 PromptBlock — 注入内容块

```python
@dataclass
class PromptBlock:
    name: str           # 段标题，如 "User Profile"
    content: str        # Markdown 内容
    cache_tier: str = "session"  # "process" | "session" | "turn"
```

### 4.4 Layer — 声明式分层

```python
class Layer:
    """声明式记忆层定义。

    Provider 通过类属性声明每层的语义、搜索和注入行为。
    系统自动收集所有 Layer 属性并影响 get_prompt_blocks()、get_tools()、prefetch()。
    """
    def __init__(self, name: str, description: str = "",
                 *, searchable: bool | str = True,
                 inject: str | None = None): ...
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | `str` | — | 层名，如 `"profile"`、`"notes"` |
| `description` | `str` | `""` | 该层的语义描述（LLM 看到） |
| `searchable` | `bool` / `"auto"` | `True` | 是否可搜索 |
| `inject` | `str` / `None` | `None` | 是否自动注入 prompt |

**`searchable` 取值：**

| 值 | 系统行为 |
|---|---|
| `False` | 不生成任何检索工具 |
| `True` | 生成 `recall_{name}` 工具，LLM 可搜 |
| `"auto"` | 生成 `recall_{name}` 工具 + **每轮自动 prefetch**，结果注入 user message |

**`inject` 取值：**

| 值 | 时机 | 适用场景 |
|---|---|---|
| `None` | 不注入 | 大量数据，按需搜索即可 |
| `"process"` | 进程启动时注入一次，永不刷新 | 固定规则 |
| `"session"` | 会话开始时注入，本轮内冻结 | 用户画像 |
| `"turn"` | 每轮对话重新注入 | 待办、动态上下文 |

**声明方式：**

```python
class MyProvider(MemoryProvider):
    # 直接用类属性声明
    profile = Layer("profile", "用户画像", searchable=True, inject="session")
    notes   = Layer("notes",   "笔记",     searchable=True, inject=None)
    alerts  = Layer("alerts",  "告警",     searchable="auto", inject="turn")

    # Layer 自动被 self.layers 收集
    # 系统据此自动生成 get_prompt_blocks()、prefetch()、get_tools()
```

---

## 5. MemoryManager — 纯代理层

```python
class MemoryManager:
    def __init__(self, provider: MemoryProvider):
        self._provider = provider

    # ── 通用读写（不假设层名）──
    def store(self, layer: str, content: str, **kw) -> dict
    def recall(self, query: str, limit=5, **kw) -> list[dict]
    def list_all(self, **kw) -> list[dict]
    def delete(self, record_id: str) -> bool
    def consolidate(self, **kw) -> int

    # ── Prompt 注入 ──
    def get_prompt_blocks(self) -> list[PromptBlock]

    # ── 工具注册 ──
    @property
    def provider(self) -> MemoryProvider
```

所有方法都是 `self._provider.xxx()` 的一行代理。`MemoryManager` 不知道任何层名，不假设后端实现。

---

## 6. PromptBlock — 分层注入

### 6.1 三级缓存策略

```
L1: Identity      ─── 进程级 ─── PromptBuilder 内部缓存
L2: Soul
L3: Bootstrap
    ─────────────────────────
    process-tier blocks       ─── Provider 返回，首次调用后冻结
    ─────────────────────────
L5: session-tier blocks       ─── Provider 返回，会话内冻结
    ─────────────────────────
L4: Channel Hint  ─── 每轮可变
    ─────────────────────────
L6: turn-tier blocks          ─── Provider 返回，每轮重新计算
```

### 6.2 Provider 控制

```python
class MyProvider(MemoryProvider):
    def get_prompt_blocks(self):
        return [
            PromptBlock("User Profile", "我是小明", cache_tier="process"),
            PromptBlock("Today Tasks", "- 写测试", cache_tier="turn"),
        ]
```

| cache_tier | 缓存策略 | 注入位置 |
|---|---|---|
| `"process"` | 进程级，首次调用后冻结，永不重新计算 | L3~L4 之间 |
| `"session"` | 会话级，`initialize()` 时冻结，本轮内写入不更新 | L5 |
| `"turn"` | 每轮重新调用 `get_prompt_blocks()` | L6（最尾部） |

---

## 7. 工具注册 — `@tool` 自注册

### 7.1 Provider 中定义

```python
class BuiltinProvider(MemoryProvider):
    def get_tools(self):
        from ....tools.decorators import tool

        @tool("recall_memory", "搜索长期记忆")
        async def recall_memory(query: str) -> str:
            records = self._store.search(query, limit=5)
            if not records:
                return "未找到相关任务记忆。"
            return "\n".join(f"- [{r['layer']}] {r['content']}" for r in records)

        @tool("remember_profile", "保存用户画像")
        async def remember_profile(content: str) -> str:
            record = self._store.store("profile", content)
            return f"已保存用户画像: {record['content']}"

        return [recall_memory, remember_profile, ...]
```

### 7.2 系统自动注册

```python
# tools/__init__.py
if context.memory_manager is not None:
    provider = context.memory_manager.provider
    for tool_obj in provider.get_tools():
        registry.register(tool_obj)
```

不再需要 `memory_tool.py`，Provider 自己就是工具的定义源。

---

## 8. Factory — 配置驱动创建

```python
# core/memory/__init__.py
def create_memory_manager(config: dict) -> MemoryManager:
    mc = config.get("memory", {})
    provider_name = mc.get("provider", "builtin")
    workspace = Path(config.get("workspace", "."))

    if provider_name == "builtin":
        provider = BuiltinProvider(
            memory_dir=workspace / "memories",
            embedding_config=mc.get("embedding"),
        )
    else:
        # 动态加载: "my_package.MyProvider" → importlib
        provider = _load_provider(provider_name, config)

    return MemoryManager(provider)
```

```yaml
# config.user.yaml
memory:
  provider: builtin                    # 内置实现
  # provider: my_memory.MyProvider     # 自定义实现
  embedding: "api://text-embedding-3-small"  # 可选：API embedding
```

---

## 9. 内置 BuiltinProvider

### 9.1 存储方案

| 特性 | 说明 |
|---|---|
| 真相源 | **Markdown 文件**（用户可直接编辑、Git 管理） |
| 索引 | SQLite FTS5（加速检索，索引丢了不影响记忆本身） |
| 向量检索 | 可选：`sqlite-vec` + 本地 `sentence-transformers` 或 API |
| 中文分词 | 可选：`jieba` 分词提升 FTS5 中文召回 |

### 9.2 文件结构

```
workspace/memories/
├── profile.md             # 用户档案（系统自动注入 prompt）
├── facts.md               # 技术事实（按需检索）
├── projects.md            # 项目上下文（按需检索）
├── reflections.md         # 经验教训（按需检索，优先级高）
└── daily/                 # 每日日志
    ├── 2026-06-10.md
    └── 2026-06-11.md
```

### 9.3 检索流水线

```
用户输入
    │
    ├─→ jieba 分词 → FTS5 关键词匹配
    │
    ├─→ (可选) embedding → sqlite-vec 语义检索
    │
    └─→ 分数融合: FTS5 0.3 + 向量 0.5 + 时间衰减 0.2
         → MMR 重排序 (λ=0.7)
         → top-5 返回
```

### 9.4 工具列表

| 工具名 | LLM 用途 | 对应层 |
|---|---|---|
| `recall_memory` | 搜索长期记忆 | 跨层 |
| `remember_profile` | 保存用户画像 | profile |
| `remember_fact` | 保存事实 | facts |
| `remember_project` | 保存项目上下文 | projects |
| `remember_reflection` | 保存经验教训 | reflections |
| `consolidate_memories` | 合并相似记录 | 跨层 |

### 9.5 Prompt 注入

`BuiltinProvider` 注入 1 段 session 级内容：

```python
PromptBlock("User Profile", "- 姓名：Zane\n...", cache_tier="session")
```

---

## 10. 自定义 Provider 接入指南

### 10.1 最小实现

只需实现 **5 个方法**即可接入：

```python
from smallshrimp.core.memory import MemoryProvider, PromptBlock
from smallshrimp.tools.decorators import tool

class MyProvider(MemoryProvider):
    """用户自己的 3 层记忆：notes / contacts / bookmarks"""

    @property
    def name(self) -> str:
        return "my_mem"

    def is_available(self) -> bool:
        return True

    # ── 核心存储（用自己的后端）──

    def store(self, layer: str, content: str, **kw) -> dict:
        # 写入到自己的数据库/文件/API
        return {"id": "...", "content": content, "layer": layer}

    def search(self, query: str, layer=None, **kw) -> list[dict]:
        # 用自己的检索逻辑
        return []

    def list_all(self, layer=None, **kw) -> list[dict]:
        return []

    # ── 工具定义（@tool 自注册）──

    def get_tools(self):
        @tool("save_note", "保存笔记到 notes 层")
        async def save_note(content: str) -> str:
            return self.store("notes", content)["id"]

        @tool("find_contacts", "搜索联系人")
        async def find_contacts(query: str) -> str:
            results = self.search(query, layer="contacts")
            return "\n".join(r["content"] for r in results)

        return [save_note, find_contacts]

    # ── (可选) 注入 prompt ──

    def get_prompt_blocks(self):
        return [
            PromptBlock("My Info", "用户自定义提示", cache_tier="turn"),
        ]
```

### 10.2 配置

```yaml
# config.user.yaml
memory:
  provider: my_package.MyProvider
```

系统自动通过 `importlib` 加载。

### 10.3 完整生命周期对接

如果需要更多控制，覆写以下方法：

| 方法 | 触发时机 | 用途 |
|---|---|---|
| `initialize(session_id)` | 每个新会话开始时 | 加载缓存快照 |
| `shutdown()` | 会话结束时 | 释放资源 |
| `close()` | 关闭 Provider | 关闭连接 |
| `prefetch(query, ...)` | 每轮自动召回 | 前置检索 |
| `sync_turn(...)` | 每轮对话结束 | 后置持久化 |
| `consolidate(**kw)` | 用户调 consolidated_memories 工具 | 合并相似记录 |
| `delete(record_id)` | 用户删除 | 删除记录 |
| `on_turn_start(...)` | 每轮开始 | 自定义回调 |
| `on_session_end(...)` | 会话结束 | 自定义回调 |
| `on_memory_write(...)` | 写入记忆 | 自定义回调 |

### 10.4 提示

- **不需要实现**所有的 ABC 方法 — 它们都有安全的默认实现
- **层名完全自由** — 用 `"notes"` / `"contacts"` / `"bookmarks"`，系统不会限制
- **工具名自由** — 工具名通过 `@tool("name", ...)` 自定义，不要和内置工具重名即可
- **Prompt 注入可选** — 不实现 `get_prompt_blocks()` 就不注入任何内容

---

## 11. 为什么这么设计

### 11.1 为什么用 Provider ABC 而不是直接继承？

```
Before: MemoryManager 硬编码 BuiltinProvider
        → 换后端必须改框架代码
        → 用户不敢升级框架

After:  MemoryManager 依赖 MemoryProvider ABC
        → 换后端只改 config.yaml
        → 用户可以捆绑自己的 Provider 到项目里
```

### 11.2 为什么工具要自注册？

```
Before: 工具定义在 tools/memory_tool.py
        → 换后端 → 工具还在 → LLM 调用到不存在的层 → 报错

After:  Provider 定义自己的工具
        → 换后端 → 工具自动换 → LLM 只能调用新后端支持的层
```

### 11.3 为什么 Prompt 要分层注入？

```
旧的注入策略：
  prompt_builder 假设只有 "User Profile" 需要注入
  → 有些 Provider 想注入多段内容（如待办列表、项目状态）
  → 只能 hack system_prompt_block() 返回拼接字符串

新的分层策略：
  Provider 返回 PromptBlock 列表 + cache_tier 标记
  → prompt_builder 自动按层级排列、缓存
  → Provider 自由控制内容和缓存策略
```

### 11.4 为什么层名不做约束？

```
旧设计：
  Literal["profile","facts","projects","reflections","sessions"]
  → 所有 Provider 都被迫用这 5 层
  → "contacts" 层得映射到 "facts"，语义丢失

新设计：
  store("contacts", content)
  → 用户用自己自然的层名
  → 检索时可以精确按层过滤
  → 不同 Provider 可以有不同的层结构
```

---

## 12. 效果与收益

### 12.1 数据

| 指标 | 旧版 | 新版 |
|---|---|---|
| MemoryManager 代码量 | 270+ 行 | ~95 行 |
| 硬编码层名 | 5 层 `Literal` | 0 |
| 类型判断（`isinstance`） | 2 处 | 0 |
| 解耦度 | Provider 耦合在构造函数里 | Provider 依赖注入 |
| 换后端需要改的文件数 | 2+ | 1（config.yaml） |
| 新增 Provider 需要改的文件数 | 3+（memory_tool + manager + ...） | 1（自己的 Provider 文件） |
| 测试通过数 | - | 11/11 ✅ |

### 12.2 关键改进

1. **Provider 可替换** — 从硬编码到依赖注入，换后端只需改配置
2. **层名解耦** — 从 `Literal` 约束到自由字符串，用户可定义自己的层
3. **工具内迁** — 从独立文件到 Provider 自描述，工具随 Provider 一起换
4. **Prompt 解耦** — 从单段硬编码到多段分层，Provider 控制注入策略
5. **ABC 简化** — 从 12+ 抽象方法到 4 个核心方法，自定义成本大幅降低

### 12.3 向后兼容

- `MemoryManager(Path)` 自动创建 `BuiltinProvider`，旧代码无需改动
- `system_prompt_block()` 默认委托 `get_prompt_blocks()`
- `remember_profile/fact/project/reflection` 已删除，请用 `store(layer, content)`
- `memory_tool.py` 已删除，工具已内迁到 `BuiltinProvider.get_tools()`
