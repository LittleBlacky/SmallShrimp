# EventBus 初始化鲁棒性 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 涉及层: Core

---

## 1. 产品概述

### 1.1 产品定位

重构 `core/eventbus.py` 中 `EventBus` 的初始化方式，消除 `try/except RuntimeError` 的静默降级模式，建立清晰的同步构造 + 异步初始化的生命周期模型。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| `__init__` 中用 `try/except RuntimeError` 兜底 Queue 创建，静默降级为 `None` | 明确区分「构造」与「启动」阶段，消除静默降级 |
| 队列为 `None` 时 `publish()` 会延迟创建，时序不可预测 | `publish()` 在 Bus 未就绪时抛出明确异常或等待就绪 |
| 无法判断 Bus 是否已启动 | 增加 `running` 状态属性和生命周期钩子 |
| 测试中需要 `asyncio.run` 环境才能正常构造 | 测试可构造后单步启动，不影响静态分析 |

### 1.3 目标用户

- **开发者 / 维护者**：EventBus 是事件驱动架构的核心基础设施，其鲁棒性影响所有依赖它的模块（Server、Worker、ChatLoop）

---

## 2. 功能范围

### 2.1 MVP（P0 — 必须实现）

| 模块 | 功能 | 说明 |
|------|------|------|
| **EventBus** | 两阶段初始化 | `__init__` 只接收配置参数、创建空队列但不启动；新增 `async start()` 启动事件处理循环 |
| **EventBus** | 状态跟踪 | 增加 `_started` 标志位，`publish()` 在未就绪时抛出 `RuntimeError("EventBus not started")` |
| **EventBus** | `__init__` 中队列创建 | 移除 try/except，直接用 `asyncio.Queue()` |
| **EventBus** | 向后兼容 | 原有的 `publish()` + `run()` 行为保持不变，仅初始化路径更明确 |

### 2.2 V1（P1 — 体验完善）

| 模块 | 功能 |
|------|------|
| **EventBus** | `publish()` 支持队列满时等待超时参数 |
| **EventBus** | `wait_until_started()` 协程方法，方便集成方等待就绪 |

### 2.3 V2（P2 — 高级功能）

| 模块 | 功能 |
|------|------|
| **EventBus** | 优雅关闭超时控制（`stop(timeout=5)`） |
| **EventBus** | 启动/停止事件钩子回调 |

---

## 3. 技术架构

### 3.1 当前实现（问题）

```python
class EventBus:
    def __init__(self, ...):
        try:
            self._queue = asyncio.Queue()  # 在无事件循环时抛出 RuntimeError
        except RuntimeError:
            self._queue = None  # 静默降级 ← 问题

    async def publish(self, event):
        if self._queue is None:
            self._queue = asyncio.Queue()  # 延迟创建
        await self._queue.put(event)
```

### 3.2 目标实现

```python
class EventBus:
    """事件总线，支持两阶段初始化。"""

    def __init__(self, pending_dir: Path | None = None, max_queue_size: int = 0):
        self._subscribers: dict[type[Event], list[Handler]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue_size)
        self._started = False
        self._pending_dir = pending_dir
        if self._pending_dir:
            self._pending_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_running(self) -> bool:
        """Bus 是否已启动。"""
        return self._started

    async def start(self) -> None:
        """启动事件处理循环。"""
        if self._started:
            return
        self._started = True
        if self._pending_dir:
            await self._recover()
        # 启动主循环
        await self._run()  # while True: event = await self._queue.get()

    async def publish(self, event: Event, timeout: float | None = None) -> None:
        """发布事件。Bus 未启动时抛出 RuntimeError。"""
        if not self._started:
            raise RuntimeError("EventBus not started")
        try:
            if timeout is not None:
                await asyncio.wait_for(self._queue.put(event), timeout=timeout)
            else:
                await self._queue.put(event)
        except asyncio.TimeoutError:
            logger.warning(f"EventBus publish timeout for {event.__class__.__name__}")

    async def stop(self, timeout: float | None = None) -> None:
        """优雅停止。"""
        self._started = False
        # 处理剩余事件...
```

---

## 4. 调用链变更

### 当前

```python
bus = EventBus()           # ⚠ 可能在无 loop 环境失败
asyncio.run(bus.run())     # 启动
```

### 目标

```python
bus = EventBus()           # ✅ 永远安全
await bus.start()          # 异步启动处理循环
await bus.publish(event)   # ✅ 明确知晓状态
await bus.stop()           # 优雅关闭
```

### 受影响的调用方

| 调用方 | 当前用法 | 变更 |
|--------|----------|------|
| `server/server.py` | `context.eventbus.run()` → `asyncio.create_task(...)` | 改为 `await context.eventbus.start()` |
| `tests/test_eventbus.py` | 直接构造后调 `publish`（依赖延迟创建） | 需调 `await bus.start()` 后再 publish |
| `cli/chat.py` | 依赖 Context 中的 EventBus | 无感知，Server/Context 适配 |
| `core/events.py` | 构造后 subscribe | 无变化 |

---

## 5. 后端 API 层设计

无新增 API。仅重构 EventBus 内部实现，对外接口做最小变更。

| 方法 | 变更类型 | 说明 |
|------|----------|------|
| `__init__` | 修改 | 移除 try/except，总是创建 Queue |
| `run()` | 废弃 → `start()` | 逻辑保留，方法名更清晰 |
| `publish()` | 修改 | 启动前调用时抛 RuntimeError |
| `start()` | 新增 | 初始化+启动事件循环 |
| `stop()` | 新增 | 优雅关闭 |

---

## 6. 测试要点

| 场景 | 说明 |
|------|------|
| 无事件循环环境构造 | 不在 `async` 函数中构造，不应抛异常 |
| publish 后再 start | 正常入队等待，start 后立即消费 |
| 未 start 就 publish | 明确抛出 `RuntimeError` |
| 多次 start | 幂等，第二次无效果 |
| start 后发布并分发 | 订阅者收到事件 |
| 优雅关闭 | stop 后队列中剩余事件的处理策略 |

---

## 7. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | 两阶段初始化重构 + 状态跟踪 + 发布前置检查 | 1d |
| P0+ | 更新 Server / Worker 调用链 | 0.5d |
| P1 | publish 超时 + wait_until_started | 0.5d |

---

## 8. 风险 & 缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 调用方未适配 start/publish 时序 | 启动后 publish 抛异常→ Agent 崩溃 | 全面搜索 `eventbus.publish` 和 `.run()` 调用点 |
| 测试用例需要批量迁移 | 测试断裂 | 提供兼容过渡期：`run()` 保留为 `start()` 别名 |

---

## 9. 附录

### 9.1 变更文件

| 文件 | 变更类型 |
|------|----------|
| `src/SmallShrimp/core/eventbus.py` | 修改 — EventBus 生命周期重构 |
| `src/SmallShrimp/server/server.py` | 修改 — 适配新的 `start()` 调用 |
| `tests/test_eventbus.py` | 修改 — 更新测试用例 |

### 9.2 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始草案 |
