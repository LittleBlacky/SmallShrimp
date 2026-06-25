# PromptBuilder 缓存自动失效 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 涉及层: Core

---

## 1. 产品概述

### 1.1 产品定位

为 `core/prompt_builder.py` 的 3 段前缀缓存（Identity/Soul/Bootstrap）增加**文件变更自动检测 + 懒失效**机制，使得 AGENT.md/SOUL.md/AGENTS.md 等文件被编辑后，无需手动调用 `reload()` 即可自动重建缓存。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| `PromptBuilder` 用 `_cached_* = None` 哨兵判断是否需要重建 | 缓存自动跟踪源文件 mtime，文件变更后自动失效 |
| 热重载后必须显式调用 `reload()` | Agent 监听自身文件变更 → 自动 `reload()` |
| `reload()` 一次性清空所有缓存，未变更文件也被重建 | 按文件粒度差异化失效，只重建必要的缓存段 |
| 无缓存命中/失效的可见性 | 增加日志和可选的 metrics 计数器 |

### 1.3 目标用户

- **Agent 维护者**：修改 AGENT.md 后新会话自动应用新配置，无需重启
- **框架开发者**：调试 Prompt 内容变化时能确认缓存是否正确失效
- **操作系统集成**：Agent 长期运行并可能被远程编辑配置文件

---

## 2. 功能范围

### 2.1 MVP（P0 — 必须实现）

| 模块 | 功能 | 说明 |
|------|------|------|
| **PromptBuilder** | 文件 mtime 跟踪 | 缓存每个源文件的 `mtime`，`build()` 时对比当前 mtime |
| **PromptBuilder** | 按段差异失效 | Identity / Soul / Bootstrap 各自独立检查来源文件 |
| **PromptBuilder** | 日志输出 | 缓存命中/失效/重建时输出 DEBUG 日志 |

### 2.2 V1（P1 — 体验完善）

| 模块 | 功能 |
|------|------|
| **PromptBuilder** | 内容 hash 替代 mtime（避免 mtime 精度不够或跨文件系统问题） |
| **PromptBuilder** | 可配置缓存策略（永久 / mtime / hash / 禁用） |
| **Agent** | 热重载时自动触发 PromptBuilder 失效检查 |

### 2.3 V2（P2 — 高级功能）

| 模块 | 功能 |
|------|------|
| **PromptBuilder** | 前缀缓存命中计数和字节统计（用于监控和调试） |
| **PromptBuilder** | Watchdog 文件监听 — 文件变更即时推送失效通知（可选替代懒检测） |

---

## 3. 技术架构

### 3.1 当前实现（问题）

```python
class PromptBuilder:
    def __init__(self, workspace: Path) -> None:
        self._cached_identity: str | None = None  # 布尔哨兵
        self._cached_soul: str | None = None       # 无法感知文件变更
        self._cached_bootstrap: str | None = None

    def reload(self) -> None:
        self._cached_identity = None   # 一次性清空全部
        self._cached_soul = None       # 文件名变更的也被清空
        self._cached_bootstrap = None
```

### 3.2 目标实现

```python
@dataclass
class CacheEntry:
    """带文件 mtime 追踪的缓存条目。"""
    content: str
    source_files: dict[Path, float]  # {path: mtime}

    def is_valid(self) -> bool:
        """检查所有源文件是否未被修改。"""
        for path, cached_mtime in self.source_files.items():
            if not path.exists():
                return False
            try:
                current_mtime = path.stat().st_mtime
                if current_mtime != cached_mtime:
                    return False
            except OSError:
                return False
        return True


class PromptBuilder:
    """组装 system prompt + mtime 驱动的自动缓存失效。"""

    def __init__(self, workspace: Path, cache_strategy: str = "mtime") -> None:
        self.workspace = workspace
        self.cache_strategy = cache_strategy  # "mtime" | "hash" | "off"

        # 按段独立缓存
        self._identity_cache: CacheEntry | None = None
        self._soul_cache: CacheEntry | None = None
        self._bootstrap_cache: CacheEntry | None = None
        self._session_memory_hashes: dict[str, int] = {}  # session_id → hash

    def build(self, state: "SessionState") -> str:
        layers = []

        # ── L1: Identity（按 mtime 自动失效）──
        if self._identity_cache and self._identity_cache.is_valid():
            identity = self._identity_cache.content
        else:
            identity = self._build_identity(state.agent.agent_def)
            self._identity_cache = self._make_cache_entry(identity, self._agent_files(state))
        layers.append(identity)

        # ── L2: Soul（同理）──
        if self._soul_cache and self._soul_cache.is_valid():
            soul = self._soul_cache.content
        else:
            soul = self._build_soul(state.agent.agent_def)
            self._soul_cache = self._make_cache_entry(soul, self._soul_files(state))
        if soul:
            layers.append(soul)

        # ── L3: Bootstrap（同理）──
        # ...
```

### 3.3 文件路径解析

```python
def _agent_files(self, state) -> list[Path]:
    """返回 Identity 缓存依赖的所有源文件。"""
    agent_dir = self.workspace / "agents" / state.agent.agent_def.id
    files = [agent_dir / "AGENT.md"]
    return files

def _soul_files(self, state) -> list[Path]:
    agent_dir = self.workspace / "agents" / state.agent.agent_def.id
    soul_file = agent_dir / "SOUL.md"
    return [soul_file] if soul_file.exists() else []

def _bootstrap_files(self) -> list[Path]:
    files = [
        self.workspace / "BOOTSTRAP.md",
        self.workspace / "AGENTS.md",
    ]
    return [f for f in files if f.exists()]

def _make_cache_entry(self, content: str, source_files: list[Path]) -> CacheEntry:
    """创建缓存条目，记录所有源文件的当前 mtime。"""
    timestamps = {}
    for f in source_files:
        try:
            timestamps[f] = f.stat().st_mtime
        except OSError:
            timestamps[f] = 0.0
    return CacheEntry(content=content, source_files=timestamps)
```

### 3.4 可选的 hash 策略

```python
def _file_hash(self, path: Path) -> str:
    """小文件的快速内容 hash（用于 hash 策略）。"""
    import hashlib
    return hashlib.md5(path.read_bytes()).hexdigest()
```

---

## 4. 调用链变更

| 调用方 | 当前 | 变更 |
|--------|------|------|
| `Agent` 构造 | `PromptBuilder(workspace)` | 无变化 |
| `AgentSession.chat()` | `prompt_builder.build(state)` | 内部自动检测，无需外部干预 |
| 配置热重载时 | 手动 `prompt_builder.reload()` | 可保留 `reload()` 作为强制清空接口 |

---

## 5. 配置项

```yaml
# config.user.yaml
prompt_cache:
  strategy: mtime           # mtime / hash / off
  debug_logging: false      # 打印缓存命中/失效日志
```

---

## 6. 测试要点

| 场景 | 说明 |
|------|------|
| 首次 build | 全部 miss → 构建所有缓存段 |
| 重复 build | 全部 hit → 不重新构建 |
| 修改 AGENT.md | Soul 缓存仍 hit，Identity 触发 miss |
| 修改 SOUL.md | Identity 缓存仍 hit，Soul 触发 miss |
| 删除 AGENT.md | `is_valid()` 返回 False → 重建 |
| 多次修改后恢复 | mtime 恢复原值 → 缓存重新有效 |
| strategy=off | 每次 build 都完全重建，不做缓存 |

---

## 7. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | CacheEntry 数据结构 + mtime 跟踪 + 按段独立失效 | 2d |
| P0+ | Agent 热重载联动 + 日志输出 | 0.5d |
| P1 | hash 策略 + 可配置缓存策略 | 1d |
| P2 | Watchdog 实时监听 + 统计指标 | 1d |

---

## 8. 风险 & 缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| mtime 精度不足（FAT32: 2s, NFS: 1s） | 缓存不能即时更新 | 默认 mtime + 可选 hash 降级 |
| 文件路径解析错误（workspace 结构变更） | 永远 miss / 永远 hit | 增加路径存在性检查和 fallback |
| 大量文件监控 Overhead | 每次 build 的成本上升 | mtime 对比是 O(1) 级操作，仅比对文件数（≤5个） |

---

## 9. 附录

### 9.1 变更文件

| 文件 | 变更类型 |
|------|----------|
| `src/SmallShrimp/core/prompt_builder.py` | 修改 — CacheEntry + mtime 跟踪 |

### 9.2 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始草案 |
