# 多 Agent 路由增强 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 涉及层: Core

---

## 1. 产品概述

### 1.1 产品定位

将 `core/routing.py` 中关键词/能力匹配的路由策略升级为支持**LLM 智能路由 + 声明式路由表 + 负载均衡**的多 Agent 路由分发系统，让消息可以被动态且精确地分发给最合适的 Agent。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| 路由策略基于简单的 Agent `capabilities` 关键词匹配 | 引入 LLM-based 路由判断，根据语义分发给最适合的 Agent |
| 无法处理模糊意图（如"帮我写个脚本"对多个 Agent 都可能） | 路由可设置 fallback 链或返回多个候选让用户选择 |
| 无 Agent 健康状态感知——已崩溃的 Agent 仍可能被路由 | 路由表检查 Agent 可用性，自动跳过不可用的 |
| 无 Agent 间的上下文共享 | 跨 Agent 共享当前会话摘要 |

### 1.3 目标用户

- **多 Agent 部署场景**——多个专业 Agent（代码/写作/数据）协同工作
- **Agent 开发者**——新增 Agent 后只需声明其 capabilities，路由自动适配
- **最终用户**——消息总能到达最合适的 Agent，获得更精准的回复

---

## 2. 功能范围

### 2.1 MVP（P0 — 必须实现）

| 模块 | 功能 | 说明 |
|------|------|------|
| **Router** | 声明式路由表 | YAML 配置 Agent 与 capabilities/description 的映射关系 |
| **Router** | LLM-based 路由 | 轻量 LLM 调用决定消息目标 Agent（可选，可降级到关键词） |
| **Router** | 健康检查 | 路由前检查 Agent 是否可用，不可用时走 fallback |
| **Router** | 路由回退 | 无匹配 Agent 时走默认 Agent（如 `pickle`） |

### 2.2 V1（P1 — 体验完善）

| 模块 | 功能 |
|------|------|
| **Router** | 多候选路由（返回 top-2 Agent 供用户选择） |
| **Router** | Agent 间共享上下文摘要 |
| **Router** | 路由缓存（同 session 内同 intent 的重复路由直接命中缓存） |

### 2.3 V2（P2 — 高级功能）

| 模块 | 功能 |
|------|------|
| **Router** | 负载均衡（多个相同 capability 的 Agent 间轮询/最少连接分发） |
| **Router** | 子 Agent 派发链记录（trace 路由决策链路） |

---

## 3. 技术架构

```
          入站消息
              │
              ▼
     ┌────────────────┐
     │   Router       │
     │   (core/routing.py)  │
     └───┬────────────┘
         │
    ┌────┴──────────────┐
    ▼                   ▼
LLM Router         Keyword Router
(首选, 高精确)      (降级, 快速)
    │                   │
    └───────┬───────────┘
            ▼
    ┌───────────────┐
    │   Agent 池    │
    │               │
    │ code_agent    │── 可用
    │ write_agent   │── 忙碌 ← 跳过
    │ data_agent    │── 可用
    │ general_agent  │── fallback
    └───────────────┘
```

### 3.1 当前路由实现

`core/routing.py` 会根据 Agent 定义的 `capabilities` 列表做关键词匹配来路由消息。

### 3.2 目标路由表（YAML 声明）

```yaml
# workspace/routing.yaml
routing:
  default_agent: pickle

  rules:
    - intent: ["编程", "代码", "调试", "bug", "函数", "Python", "JavaScript"]
      agent: coder
      description: "代码编写与调试"

    - intent: ["写作", "文章", "文档", "报告", "翻译"]
      agent: writer
      description: "文章与文档写作"

    - intent: ["数据", "分析", "图表", "SQL", "可视化"]
      agent: data_analyst
      description: "数据分析与可视化"

    - intent: ["系统", "运维", "部署", "Docker", "服务器"]
      agent: ops
      description: "运维与部署"
```

### 3.3 Router 核心

```python
# core/routing.py（改写）

@dataclass
class RouteResult:
    agent_id: str
    confidence: float
    method: str  # "llm" | "keyword" | "fallback"
    candidates: list[tuple[str, float]] | None = None

class AgentRouter:
    """多 Agent 路由分发器。"""

    def __init__(
        self,
        agents: dict[str, "Agent"],
        routing_config: dict | None = None,
        llm_provider: "LLMProvider | None" = None,
    ):
        self._agents = agents
        self._config = routing_config or {}
        self._llm = llm_provider
        self._rules = self._load_rules(routing_config)
        self._cache: dict[str, RouteResult] = {}  # session_id → last route

    async def route(self, message: str, session_id: str) -> RouteResult:
        """路由消息到最合适的 Agent。"""
        # 1. LLM 路由（优先）
        if self._llm and self._is_llm_routing_enabled():
            result = await self._llm_route(message)
            if result and result.confidence > 0.6:
                return result

        # 2. 关键词路由
        result = self._keyword_route(message)
        if result:
            return result

        # 3. Fallback 到默认
        return RouteResult(
            agent_id=self._config.get("default_agent", "pickle"),
            confidence=0.0,
            method="fallback",
        )

    async def _llm_route(self, message: str) -> RouteResult | None:
        """调轻量 LLM 判断消息意图 + 选择 Agent。"""
        candidates_desc = "\n".join(
            f"- {aid}: {agent.agent_def.description}"
            for aid, agent in self._agents.items()
            if self._is_available(aid)
        )
        prompt = f"""给定以下候选 Agent，判断哪一个是处理用户消息的最佳选择。
仅返回 Agent ID，不要解释。

可用 Agent：
{candidates_desc}

用户消息：{message}"""

        response = await self._llm.chat([{"role": "user", "content": prompt}])
        chosen = response.get("content", "").strip()
        if chosen in self._agents:
            return RouteResult(agent_id=chosen, confidence=0.8, method="llm")
        return None

    def _keyword_route(self, message: str) -> RouteResult | None:
        """基于关键词的快速路由。"""
        msg_lower = message.lower()
        best_match = None
        best_score = 0

        for rule in self._rules:
            score = sum(1 for kw in rule.intent if kw.lower() in msg_lower)
            if score > best_score:
                best_score = score
                best_match = rule.agent

        if best_match and best_score > 0:
            return RouteResult(
                agent_id=best_match,
                confidence=min(0.5 + best_score * 0.1, 0.9),
                method="keyword",
            )
        return None

    def _is_available(self, agent_id: str) -> bool:
        """检查 Agent 是否可用（未崩溃、未过载）。"""
        agent = self._agents.get(agent_id)
        if not agent:
            return False
        # 检查 session 数是否超限
        if hasattr(agent, "agent_def") and hasattr(agent.agent_def, "max_concurrency"):
            active_sessions = getattr(agent, "_active_sessions", set())
            if len(active_sessions) >= agent.agent_def.max_concurrency:
                return False
        return True
```

---

## 4. 调用链变更

| 调用方 | 当前 | 变更 |
|--------|------|------|
| `cli/chat.py` | 直接创建指定 Agent | 可通过 Router 动态解析目标 Agent |
| `server/workers/agent.py` | 固定 Agent 处理 | 消息先过 Router 再分发 |
| `core/agent_loader.py` | 加载全部 Agent | 引擎预加载所有 Agent，Router 按需激活 |

---

## 5. 配置项

```yaml
# config.user.yaml
routing:
  default_agent: pickle
  llm_routing:
    enabled: true
    provider: ""           # 同主 LLM 或独立轻量模型
    model: ""              # 如 "deepseek/deepseek-chat"
    confidence_threshold: 0.6
  cache:
    enabled: true
    ttl_seconds: 300       # 同 session 内路由结果缓存 5 分钟
```

---

## 6. 测试要点

| 场景 | 说明 |
|------|------|
| 关键词匹配 | 消息"帮我写个 Python 脚本"路由到 coder |
| LLM 路由 | 复杂意图（"我的数据需要可视化"）LLM 路由到 data_analyst |
| 降级 | LLM 不可用时自动降级到关键词 |
| 健康检查 | coder 崩溃了 → 路由到 fallback（pickle） |
| 路由缓存 | 同 session 内重复 intent 命中缓存 |

---

## 7. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | 声明式路由表 YAML 加载 + 关键词路由 + 健康检查 + fallback | 2d |
| P0+ | LLM 路由实现 + 自动降级 | 2d |
| P1 | 多候选路由 + 上下文摘要共享 + 路由缓存 | 2d |
| P2 | 负载均衡 + 路由链路追踪 | 2d |

---

## 8. 风险 & 缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 路由延迟 | 消息响应变慢 | 轻量模型（快模型）+ 关键词路由作并行降级 |
| LLM 路由成本 | 每条消息额外一次 LLM 调用 | 路由缓存 + 可禁用的开关 + 关键词路由兜底 |
| Agent 冷启动 | 首次使用未加载 | AgentLoader 支持懒加载 + 预热 |

---

## 9. 附录

### 9.1 参考产品

- **LangChain Agent Router**：`RunnableBranch` 条件路由
- **Semantic Kernel**：`Planning/IPlanner` 多 Agent 编排

### 9.2 变更文件

| 文件 | 变更类型 |
|------|----------|
| `src/SmallShrimp/core/routing.py` | 重写 — 完整路由系统 |
| `src/SmallShrimp/utils/def_loader.py` | 修改 — 加载 routing.yaml |
| `src/SmallShrimp/server/workers/agent.py` | 修改 — 接入路由 |
| `src/SmallShrimp/cli/chat.py` | 修改 — 可选路由 |

### 9.3 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始草案 |
