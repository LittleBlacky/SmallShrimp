# SmallShrimp System Prompt 设计文档

> System Prompt 的分层组装与 Prefix Cache 策略。

---

## 目录

1. [问题](#1-问题)
2. [当前 PromptBuilder 的 5 层结构](#2-当前-promptbuilder-的-5-层结构)
3. [三段式缓存方案](#3-三段式缓存方案)
4. [各层的缓存归属与更新时机](#4-各层的缓存归属与更新时机)
5. [PromptBuilder + MemoryManager 协作](#5-promptbuilder--memorymanager-协作)
6. [写入可见性时间线](#6-写入可见性时间线)
7. [配置项](#7-配置项)
8. [实现注意事项](#8-实现注意事项)

---

## 1. 问题

### 1.1 当前代码的问题

当前 `PromptBuilder.build()` 每次构建 system prompt 时实时组装：

```python
def build(self, state):
    layers = []
    layers.append(agent_md)        # Layer 1: Identity
    layers.append(soul_md)          # Layer 2: Soul
    layers.append(bootstrap)        # Layer 3: Bootstrap
    layers.append(channel_hint)     # Layer 4: Channel
    layers.append(profile_block)    # Layer 5: Profile（每次查库）
    return "\n\n".join(layers)      # ← 每轮字节不同 → cache miss
```

**后果**：每一轮 system prompt 的字节都不一样（尤其是 `profile_block`），导致 LLM provider 的 prefix cache 每次都不命中。平均增加 300-500ms 首 token 延迟。

### 1.2 Provider prefix cache 特性

| Provider | 缓存机制 | 命中条件 | 缓存大小 |
|----------|---------|---------|---------|
| Anthropic | Prompt Caching | 前缀 1024 tokens 相同 | 4K tokens breakpoints |
| OpenAI | Prompt Caching | 前缀完全相同 | 1024 tokens 起 |
| Google Gemini | Context Caching | 前缀完全相同 | 32K tokens 起 |
| 本地模型 | KV Cache | 前缀完全相同 | 取决于实现 |

**关键**：只要 system prompt 前 N 个 token 不变，prefix cache 就有效。变的是**尾部可变内容**（如每轮的 prefetch 结果）。

---

## 2. 当前 PromptBuilder 的 5 层结构

| 层 | 来源 | 内容 | 变化频率 |
|----|------|------|---------|
| L1: Identity | AGENT.md body | Agent 身份、能力描述 | 部署时一次 |
| L2: Soul | SOUL.md（可选） | 人格设定、语气风格 | 部署时一次 |
| L3: Bootstrap | BOOTSTRAP.md + AGENTS.md | 工作区引导、cron 列表 | 工作区变更时 |
| L4: Channel Hint | EventSource | 平台/频道上下文 | 每轮 |
| L5: User Profile | MemoryManager.get_profile() | 用户画像 | 每轮（当前） |

### 2.1 Layer 4 是 cache 破坏者

```
Layer 4: "- 用户叫张三\n- 偏好深色模式"  ← 可能每轮不同

→ 只要可变内容嵌入 system prompt 中间，前缀缓存就无效了
```

---

## 3. 三段式缓存方案

### 3.1 方案图示

```
┌──────────────────────────────────────────────────────────────────┐
│  █████ 永久缓存段 █████                                          │
│  ─────────────────────────────────────                           │
│  构建时机：部署/加载时一次，之后缓存到内存                           │
│  缓存位置：PromptBuilder 实例变量                                  │
│  缓存期限：进程生命周期                                           │
│                                                                  │
│                                                                  │
│  ← 这段前缀在整个进程生命周期内字节级稳定，prefix cache 永远命中    │
├──────────────────────────────────────────────────────────────────┤
│  █████ 每轮冻结段 █████                                          │
│  ─────────────────────────────────────                           │
│  构建时机：Session 建立时 initialize() 一次，缓存到会话结束         │
│  缓存位置：MemoryProvider 实例变量                                 │
│  缓存期限：当前会话生命周期                                        │
│                                                                  │
│  L5: User Profile 快照  ← MemoryProvider.system_prompt_block()    │
│                                                                  │
│  ← 本轮内 Correction 写 SQLite 但不更新此快照                      │
│  ← 新 profile 从下一轮/新会话开始可见                               │
│  ← profile 极少变化，命中率高                                      │
├──────────────────────────────────────────────────────────────────┤
│  █████ 每轮可变段（system prompt 尾部，不影响前缀缓存）            │
│  ─────────────────────────────────────                           │
│  构建时机：每轮组装                                              │
│                                                                  │
│  L4: Channel Hint     → 每轮可能不同，放此处                      │
├──────────────────────────────────────────────────────────────────┤
│  █████ 零缓存段（不在 system prompt 中）                          │
│  ─────────────────────────────────────                           │
│  注入位置：user message 头部或尾部，不碰 system prompt             │
│                                                                  │
│  Prefetch 结果（含 Reflections） → MemoryProvider.prefetch() → user message 尾部  │
│  Intent Hint + 时间戳            → detect_memory_intent() → user message 头部     │
│                                                                  │
│  ← 这些内容每轮不同，但放在 user message 中，不影响 system prompt  │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 完整 system prompt 的字节布局

```
[L1 Identity]         ← 永久缓存段（进程生命周期）
[L2 Soul]             ← 永久缓存段
[L3 Bootstrap]        ← 永久缓存段
─── cache breakpoint ──
[L5 Profile 快照]     ← 每轮冻结段（会话生命周期）
─── cache breakpoint ──
[L4 Channel Hint]     ← 每轮可变段
```

---

## 4. 各层的缓存归属与更新时机

### 4.1 永久缓存段

| 层 | 缓存字段 | 更新时机 | 实现方式 |
|----|---------|---------|---------|
| L1 Identity | `_cached_identity` | `PromptBuilder.__init__()` 或首次 `build()` | 读文件一次，存实例变量 |
| L2 Soul | `_cached_soul` | 同上 | 读文件一次，存实例变量 |
| L3 Bootstrap | `_cached_bootstrap` | 同上，或 `reload()` 方法 | 读文件一次，存实例变量 |

```python
class PromptBuilder:
    def __init__(self, workspace: Path):
        self._workspace = workspace
        # 永久缓存段：进程生命周期内不变
        self._cached_identity: str | None = None
        self._cached_soul: str | None = None
        self._cached_bootstrap: str | None = None

    def _ensure_cache(self) -> None:
        """延迟加载：首次 build() 时读取并缓存。"""
        if self._cached_identity is None:
            self._cached_identity = self._load_identity()
        if self._cached_soul is None:
            self._cached_soul = self._load_soul()
        if self._cached_bootstrap is None:
            self._cached_bootstrap = self._load_bootstrap()
```

### 4.2 每轮冻结段

| 层 | 缓存字段 | 更新时机 | 实现方式 |
|----|---------|---------|---------|
| L5 Profile | `_snapshot_profile` | `MemoryProvider.initialize(session_id)` | 查 SQLite 一次，存内存 |

> **为何不缓存 Reflections？** Reflections（失败教训、行为反思）变化频率高，每轮都可能写入，
> 若放入冻结段会导致 session 内 prefix cache 持续失效。
> 改为走 **prefetch 按需检索**，在 user message 尾部零缓存段注入，不影响 system prompt。

**缓存契约**：

- `initialize()` 时从 SQLite 读取 Profile，之后 `system_prompt_block()` 只返回缓存
- 本轮内 Correction → Profile 写入 SQLite，但**不更新**缓存
- 新 Profile 从**下一轮或新会话**开始可见
- `refresh_snapshot()` 方法供 `on_session_switch` / `on_session_end` 调用

### 4.3 每轮可变段

| 层 | 是否缓存 | 原因 |
|----|---------|------|
| L4 Channel Hint | 不缓存 | 取决于本轮 source |

### 4.4 零缓存段（在 user message 中）

| 内容 | 注入位置 | 原因 |
|------|---------|------|
| Prefetch 结果 | user message 尾部 | 不碰 system prompt 字节 |
| Intent Hint | user message 头部 | 同上 |

---

## 5. PromptBuilder + MemoryManager 协作

### 5.1 组装流程

```
Session Start:
  PromptBuilder.__init__()
    → 永久缓存段加载（进程唯一，下次复用）
  
  MemoryManager.initialize(session_id)
    → BuiltinProvider.initialize()
      → 查 SQLite：profile → 缓存到 _snapshot

  PromptBuilder.build(state):
    → 永久缓存段（已缓存，字节稳定）
    + MemoryProvider.system_prompt_block()（profile 快照，字节稳定）
    + 每轮可变段（channel）
    = system prompt（前 3 段字节稳定，prefix cache 有效）

Each Turn:
  user message = IntentHint? + PrefetchBlock(含 Reflections)? + 用户原始消息
    → 不碰 system prompt 字节

Turn End:
  Correction → 写 Profile SQLite（不更新缓存）
  Failure → 写 Reflections SQLite（走 prefetch 供下轮检索）
  sync_turn() → 持久化本轮

Next Session:
  MemoryManager.initialize(new_session_id)
    → 重新查库 → 新快照
```

### 5.2 PromptBuilder 重构

```python
class PromptBuilder:
    def __init__(self, workspace: Path):
        self._workspace = workspace
        self._ensure_cache()

    def _ensure_cache(self):
        """进程级缓存：仅加载一次。"""
        ...

    def build(self, state: "SessionState") -> str:
        """构建 system prompt，缓存感知。"""
        layers = []

        # ── 永久缓存段（字节稳定） ──
        layers.append(self._cached_identity)       # L1
        if self._cached_soul:
            layers.append(self._cached_soul)       # L2
        if self._cached_bootstrap:
            layers.append(self._cached_bootstrap)  # L3

        # ── 每轮冻结段（MemoryProvider 缓存快照） ──
        memory_block = self._build_memory_block(state)
        if memory_block:
            layers.append(memory_block)            # L5

        # ── 每轮可变段（system prompt 尾部） ──
        if state.source:
            layers.append(self._build_channel_hint(state.source))  # L4

        return "\n\n".join(layers)

    def _build_memory_block(self, state) -> str:
        """从 MemoryProvider 取缓存快照，不查库。"""
        memory_manager = getattr(state.agent, "memory_manager", None)
        if not memory_manager:
            return ""
        return memory_manager.system_prompt_block()
```

---

## 6. 写入可见性时间线

```
                  SQLite 写入             system prompt 缓存
                  ───────────             ──────────────────

Session A Turn 1:
  User: "我叫张三"
  Correction HIGH → profile: "张三"      ← 写库
                                          缓存: (空)
  User Message: [时间戳] + [hint] + "我叫张三"
  System Prompt: [永久段] + [profile: 空] + [channel]
  → LLM 看到的是空 profile，但 user message 中有 hint

Session A Turn 2:
  User: "深色模式"
  Prefetch: 无相关记忆
  System Prompt: [永久段] + [profile: 空] + [channel]  ← cache HIT!
  → profile 缓存仍为空，但 history 中有 Turn 1 的纠正

Session B（新会话）:
  initialize() → 查库 → profile: "张三" ← 新快照
  System Prompt: [永久段] + [profile: "张三"] + [channel]
  → 跨会话记住了

多轮写入同一 profile:
  Turn 1: "用户叫张三"        → profile: "张三"
  Turn 2: "用户偏好深色模式"   → profile: "张三\n偏好深色模式"
  Turn 3: "用户用 Windows"    → profile: "张三\n偏好深色模式\n用 Windows"

  ★ 但 system prompt 中的 profile 快照在 session 内不变
  ★ LLM 通过 history 中的工具调用结果了解到所有 profile 条目
  ★ 缓存快照仅用于下一轮 system prompt 注入

Reflections（失败教训）同理，但走 prefetch 而非 system prompt：
  Turn 1: 工具调用出错 → Correction LOW → reflections 写入 SQLite
  Turn 2: Prefetch 检索到该 reflection → user message 尾部注入
  → 不碰 system prompt 字节，不破坏 prefix cache
```

---

## 7. 配置项

```yaml
prompt:
  cache:
    enabled: true
    refresh_on_session_end: true
    refresh_on_session_switch: true

memory:  # 只在 memory-layer-design.md 中定义，system prompt 引用
  builtin:
    max_profile_in_prompt: 10
    max_prefetch_results: 5
    max_prefetch_chars: 1500
```

---

## 8. 实现注意事项

### 8.1 Prefix Cache 对齐

如果使用 Anthropic，需要在永久缓存段末尾显式插入 `cache_control`：

```python
# Anthropic API 请求构造
{
    "role": "system",
    "content": [
        {"type": "text", "text": permanent_block},
        {"type": "text", "text": "---cache_breakpoint---"},  # 实际对应 Anthropic API
        {"type": "text", "text": frozen_block},
        {"type": "text", "text": variable_block},
    ]
}
```

### 8.2 延迟加载

永久缓存段应该在 `PromptBuilder.__init__()` 时延迟加载（懒加载），而非构造函数中强制读取。确保即使没有 BOOTSTRAP.md 也不会报错。

### 8.3 热重载

如果用户修改了 AGENT.md 或 BOOTSTRAP.md，应提供 `reload()` 方法清空缓存：

```python
def reload(self) -> None:
    """清空进程级缓存（AGENT.md / SOUL.md / BOOTSTRAP.md 变更时调用），下次 build() 时重新读取。"""
    self._cached_identity = None
    self._cached_soul = None
    self._cached_bootstrap = None
```

### 8.4 安全边界

无论缓存策略如何，**user message 注入的 prefetch 结果必须经 fence sanitization**，防止用户通过写入恶意 content 伪装成 system prompt 指令。参考 ZLAgent 的 `sanitize_untrusted()`：

```python
def _fence_prefetch_block(results: list[dict]) -> str:
    """给 prefetch 结果加 fence，防止内容注入。"""
    lines = ["## Relevant Memory Context"]
    lines.append("(以下内容来自记忆库，可作为参考。)")
    for r in results:
        # 转义 <memory-context> 标签
        safe = r['content'].replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f"- [{r['layer']}] {safe}")
    return "\n".join(lines)
```
