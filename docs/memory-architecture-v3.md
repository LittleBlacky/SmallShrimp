# SmallShrimp 记忆层架构设计 v3

> 最终更新: 2026-06-16
> 基于 v2 重构 + Phase 1~5 改进

---

## 目录

1. [架构总览](#1-架构总览)
2. [核心原则](#2-核心原则)
3. [Provider 插件系统](#3-provider-插件系统)
4. [MemoryManager — 纯代理层](#4-memorymanager--纯代理层)
5. [声明式 Layer 分层](#5-声明式-layer-分层)
6. [内置 BuiltinProvider](#6-内置-builtinprovider)
7. [存储层 — Markdown 文件真相源 + SQLite FTS5](#7-存储层--markdown-文件真相源--sqlite-fts5)
8. [自动写入管线](#8-自动写入管线)
9. [上下文工程 — 8 个辅助模块](#9-上下文工程--8-个辅助模块)
10. [Prompt 注入结构](#10-prompt-注入结构)
11. [配置项](#11-配置项)
12. [自定义 Provider 接入](#12-自定义-provider-接入)

---

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│  config.yaml → create_memory_manager() → MemoryManager → Provider  │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  MemoryManager（纯代理层）                                           │
│  store / recall / list_all / delete / consolidate                  │
│  initialize / prefetch / sync_turn / get_prompt_blocks / get_tools │
└──────┬──────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  MemoryProvider (ABC)                                               │
│  ← BuiltinProvider  (内置, SQLite + FTS5 + 可选向量)                 │
│  ← HonchoProvider   (第三方记忆后端)                                 │
│  ← Mem0Provider     (第三方记忆后端)                                 │
│  ← 自定义 (config 里写 dotted path)                                  │
└─────────────────────────────────────────────────────────────────────┘
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
┌──────────────┐   ┌──────────────────┐   ┌──────────────────────┐
│ Agent 集成    │   │ PromptBuilder    │   │ 8 个辅助模块          │
│ chat() 中调用 │   │ get_prompt_      │   │ TopicSegmenter       │
│ initialize() │   │ blocks() →       │   │ ConversationBuffer   │
│ prefetch()   │   │ 按 cache_tier     │   │ TodoTracker          │
│ sync_turn()  │   │ 分层注入          │   │ ToolStateMemory      │
│              │   │                  │   │ ReflectionEngine     │
└──────────────┘   └──────────────────┘   │ DreamingEngine       │
                                          │ PriorityResolver     │
                                          │ ContextGuard         │
                                          └──────────────────────┘
```

---

## 2. 核心原则

| 原则 | 说明 |
|------|------|
| **Provider 插件化** | 换记忆后端只需改一行 `config.yaml`，MemoryManager 只依赖 ABC |
| **层名可自定义** | 每个 Provider 用 `Layer()` 声明自己的层，系统不假设任何层名 |
| **工具自注册** | Provider 用 `@tool` 定义工具，自动注册到 ToolRegistry |
| **分层注入** | `PromptBlock` 分 `process/session/turn` 三级缓存，保护前缀缓存 |
| **约束不压缩** | constraints 层永远不参与 Autocompact 压缩流程 |
| **最小接口** | 实现自定义后端只需 4 个核心方法：`store/search/list_all/get_tools` |

---

## 3. Provider 插件系统

### MemoryProvider ABC

```python
class MemoryProvider(ABC):
    # ── 必须实现 ──
    @abstractmethod
    def name(self) -> str: ...
    @abstractmethod
    def is_available(self) -> bool: ...
    @abstractmethod
    def store(self, layer, content, **kwargs) -> dict: ...
    @abstractmethod
    def search(self, query, layer=None, **kwargs) -> list[dict]: ...
    @abstractmethod
    def list_all(self, layer=None, **kwargs) -> list[dict]: ...
    @abstractmethod
    def get_tools(self) -> list: ...

    # ── 有默认实现 ──
    def initialize(self, session_id): ...
    def shutdown(self): ...
    def close(self): ...
    def prefetch(self, query, session_id=""): ...
    def sync_turn(self, ...): ...
    def delete(self, record_id): ...
    def consolidate(self, **kwargs): ...
    def get_prompt_blocks(self) -> list[PromptBlock]: ...
    def system_prompt_block(self) -> str: ...
```

### Factory

```yaml
memory:
  provider: builtin           # 或 "my_module.MyProvider"
  embedding: local            # local/api://model
```

`create_memory_manager(config)` 根据 `provider` 字段：
- `"builtin"` → 创建 `BuiltinProvider`
- 其他 → `importlib.import_module` 动态加载

---

## 4. MemoryManager — 纯代理层

```python
class MemoryManager:
    def __init__(self, provider: MemoryProvider | str | Path): ...
    # 全部委托给 provider
    def store(self, layer, content, **kwargs) -> dict: ...
    def recall(self, query, limit=5, **kwargs) -> list[dict]: ...
    def list_all(self, **kwargs) -> list[dict]: ...
    def delete(self, record_id) -> bool: ...
    def consolidate(self, **kwargs) -> int: ...
    def initialize(self, session_id): ...
    def prefetch(self, query, session_id=""): ...
    def sync_turn(self, ...): ...
    def get_prompt_blocks(self) -> list[PromptBlock]: ...
```

---

## 5. 声明式 Layer 分层

### Layer 描述符

```python
class Layer:
    def __init__(self, name, description="",
                 *, searchable=True | "auto", inject=None | "process" | "session" | "turn")
```

- `searchable=True` → 生成 `recall_{name}` 工具
- `searchable="auto"` → 生成工具 + 每轮自动 prefetch
- `inject="session"` → `initialize()` 时冻结，session 级别缓存
- `inject="process"` → 进程级别永不刷新
- `inject="turn"` → 每轮重新注入

### PromptBlock

```python
@dataclass
class PromptBlock:
    name: str       # 段标题
    content: str    # Markdown
    cache_tier: str # "process" | "session" | "turn"
```

---

## 6. 内置 BuiltinProvider

### 5 层声明

| Layer | searchable | inject | 作用 |
|-------|-----------|--------|------|
| **profile** | True | `"session"` | 用户档案，会话缓存，自动注入 prompt |
| **facts** | True | None | 技术事实，按需检索 |
| **projects** | True | None | 项目上下文，按需检索 |
| **reflections** | `"auto"` | None | 经验教训，每轮自动召回 |
| **constraints** | True | `"session"` | 硬性约束，排在 profile 之前注入，不参与压缩 |

### 快照缓存机制

```
initialize() 时:
  _snapshot_profile    ← list_all("profile")[:20]
  _snapshot_constraints ← list_all("constraints")

get_prompt_blocks() 返回:
  1. Hard Constraints (constraints 快照) ← 保证前缀缓存稳定
  2. User Profile (profile 快照)         ← initialize() 后不刷新
```

### 7 个 @tool

| 工具 | 写入层 | 说明 |
|------|--------|------|
| `recall_memory` | 跨层 | 搜索 facts/projects/reflections |
| `remember_profile` | profile | 用户身份、偏好、纠正 |
| `remember_fact` | facts | 跨会话知识 |
| `remember_project` | projects | 项目相关记忆 |
| `remember_reflection` | reflections | 失败教训、行为修正 |
| `remember_constraint` | constraints | 否定条件、数字约束 |
| `consolidate_memories` | 跨层 | 合并相似记录 |

---

## 7. 存储层 — Markdown 文件真相源 + SQLite FTS5

### MarkdownStore

```
写入: .md 文件追加 bullet → SQLite FTS5 索引同步 → 可选向量索引
检索: FTS5 (jieba OR) → 可选 sqlite-vec 向量 → MMR 重排序 → 时间衰减
```

### 层级文件映射

| 层 | 文件 |
|----|------|
| profile | `memories/profile.md` |
| facts | `memories/facts.md` |
| projects | `memories/projects.md` |
| reflections | `memories/reflections.md` |
| constraints | `memories/constraints.md` |
| sessions | `memories/daily/YYYY-MM-DD.md` |

### 检索

```python
def search(self, query, layer=None, limit=10, use_hrr=False):
    # 1. jieba 分词 → FTS5 OR 查询
    # 2. 可选向量召回（sqlite-vec）
    # 3. MMR 重排序（平衡相关性和多样性）
    # 4. 时间衰减（半衰期 30 天）
```

### 去重

三段式去重：精确匹配 → 子串匹配 → 模糊匹配（`SequenceMatcher >= 0.92`）。
合并规则：取更长 content，importance/confidence 取 max。

---

## 8. 自动写入管线

```
Turn Start:
  User Message
    ├── Correction Detection → HIGH → 直接写 profile（不经过 LLM）
    │
    ├── Intent Detection → HIGH → 注入 hint → 后续 Post-turn review
    │
    └── Prefetch → reflections(searchable="auto") 自动召回
                   注入 user message 尾部

Turn Execution:
    ├── LLM 调 recall_memory → keyword top-15 → LLM 重排序 top-5
    ├── LLM 调 remember_*    → 手动写对应层
    ├── ToolStateMemory     → 去重检查，跳过重复调用
    └── ContextGuard        → 4 级压缩（Budget → Snip → Microcompact → Autocompact）

Turn End:
    ├── FailureLearner → 自动写 reflections（importance=7）
    ├── sync_turn      → 持久化到 sessions 层
    └── ConversationBuffer → 记录本轮轮次
```

---

## 9. 上下文工程 — 8 个辅助模块

| 模块 | 文件 | 核心功能 |
|------|------|---------|
| **TopicSegmenter** | `topic_segmenter.py` | 话题分段存储: `换个话题`创建新话题, `回到刚才`回溯, follow-up 连续性兜底 |
| **ConversationBuffer** | `conversation_buffer.py` | 按轮次组织对话, 溢出时选旧轮次供摘要替换 |
| **TodoTracker** | `todo_tracker.py` | 多步任务进度追踪, 已完成折叠节省 token |
| **ToolStateMemory** | `tool_state.py` | 参数指纹去重, 失败追踪, 工具统计 |
| **ReflectionEngine** | `reflection.py` | 重要性累计触发, 归纳→抽象→策略推导, confidence 过滤 |
| **DreamingEngine** | `dreaming.py` | 对立词冲突检测 (5/5=100%), 30天衰减, 跨会话关联 |
| **PriorityResolver** | `priority_resolver.py` | 5 级优先级, 槽位分离 Prompt 组装 |
| **ContextGuard** | `context_guard.py` | 4 级压缩, Autocompact 分级指令(约束原文保留) |

### 模块关系

```
ContextGuard  ← 全局上下文窗口管理（4 级压缩）
    │
    ├── ConversationBuffer ← 轮次级管理（哪个轮次该被摘要）
    │
    ├── TopicSegmenter    ← 话题级管理（活跃/暂停话题上下文）
    │
    ├── TodoTracker       ← 任务级管理（当前进度锚点）
    │
    └── PriorityResolver  ← 信息源级管理（什么信息排前面）

ToolStateMemory  ← 工具调用级（去重 + 失败学习）
ReflectionEngine ← 会话间隙级（高层次反思）
DreamingEngine   ← 后台任务级（离线整合）
```

---

## 10. Prompt 注入结构

```
【系统规则】                           ← PriorityResolver
【硬性约束 Hard Constraints】          ← constraints 快照（session 级缓存）
【实时状态】                           ← PriorityResolver
【User Profile】                       ← profile 快照（session 级缓存）
【认知洞察 Insights】                  ← ReflectionEngine（高 confidence）
【任务进度】                           ← TodoTracker
【话题状态】                           ← TopicSegmenter
🔄 话题 A（进行中）
⏸ 话题 B（已暂停）

← user message（含 prefetch 注入的记忆）→
【已执行操作】                         ← ToolStateMemory

← assistant response →
```

---

## 11. 配置项

```yaml
memory:
  enabled: true
  provider: builtin                     # 或 "my_module.MyProvider"

  builtin:
    max_profile_in_prompt: 20           # profile 注入上限
    max_prefetch_results: 5             # prefetch 结果数
    max_prefetch_chars: 1500            # prefetch token 预算
    session_retention_days: 7           # 会话保留天数
    correction_auto_write: true         # 纠正自动写入 profile
    failure_auto_write: true            # 失败自动写入 reflections

  embedding: local                      # local / api://模型名 / null

context_guard:
  token_threshold: 160000               # 触发压缩的 token 阈值
  context_window: 200000                # 上下文窗口大小
```

---

## 12. 自定义 Provider 接入

只需 4 个核心方法：

```python
from SmallShrimp.core.memory import MemoryProvider, Layer

class MyProvider(MemoryProvider):
    notes = Layer("notes", "自定义笔记", searchable=True, inject="session")

    @property
    def name(self): return "my_provider"

    def is_available(self): return True

    def store(self, layer, content, **kwargs) -> dict:
        # 写入后端（SQL/Redis/文件...）
        return {"id": "...", "content": content, "layer": layer}

    def search(self, query, layer=None, **kwargs) -> list[dict]:
        return []  # 检索实现

    def list_all(self, layer=None, **kwargs) -> list[dict]:
        return []  # 全量列出

    def get_tools(self) -> list:
        from SmallShrimp.tools.decorators import tool
        @tool(description="搜索")
        async def recall_notes(query: str) -> str:
            return "..."
        return [recall_notes]
```

在 `config.yaml` 中：

```yaml
memory:
  provider: my_module.MyProvider
```
