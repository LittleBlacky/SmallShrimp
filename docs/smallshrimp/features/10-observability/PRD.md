# 可观测性 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 涉及层: Core / Server

---

## 1. 产品概述

### 1.1 产品定位

为 SmallShrimp 框架引入 **OpenTelemetry 分布式追踪** + **结构化日志**，让开发者和管理员能够通过追踪链路（Agent 轮次 → 工具调用 → LLM 调用 → 记忆操作）定位性能瓶颈、排查故障、监控系统健康状态。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| 日志只有 `logging.info`/`error`，无结构化和上下文关联 | OpenTelemetry spans 实现端到端追踪，每个 Agent 轮次一个 trace |
| 无法查看单个工具调用的耗时和参数 | 每个工具调用一个子 span，含耗时、入参、返回摘要 |
| 无法量化 LLM 调用延迟和 token 消耗 | LLM 调用 span 含 prompt_tokens / completion_tokens / latency |
| 无性能基线，无法对比优化前后 | span 数据可导出到 Jaeger/Grafana 做可视化分析 |
| 多 Agent 场景下无法串联消息流 | trace_id 跨 Agent 传播，完整可见调用链路 |

### 1.3 目标用户

- **框架维护者**：开发/调试时定位性能瓶颈
- **服务运维**：生产环境监控 Agent 健康状况、异常检测
- **高级用户**：了解自己 Agent 的工具使用和 token 消耗分布

---

## 2. 功能范围

### 2.1 MVP（P0 — 必须实现）

| 模块 | 功能 | 说明 |
|------|------|------|
| **Tracer** | OTel 初始化 | `init_tracer(service_name="smallshrimp")` 配置导出器 |
| **AgentSession** | trace 包围 | 每次 `chat()` 创建一个 trace，每个工具调用一个 span |
| **LLMProvider** | LLM 调用 span | 含 model、prompt_tokens、completion_tokens、latency |
| **ToolRegistry** | 工具调用 span | 含 tool_name、duration、args（脱敏）、result_size |

### 2.2 V1（P1 — 体验完善）

| 模块 | 功能 |
|------|------|
| **结构化日志** | JSON 格式日志（`loguru` 或 `structlog`）代替纯文本 |
| **内存/GC 指标** | Agent 轮次前后记录 memory_usage、gc_stats |
| **Metrics** | Prometheus 指标：工具调用计数、LLM token 总量、错误率 |

### 2.3 V2（P2 — 高级功能）

| 模块 | 功能 |
|------|------|
| **健康检查端点** | FastAPI `/healthz` 返回 trace 数据概要 |
| **可视化仪表盘** | 集成 Grafana 面板模板 |
| **自动 Profiling** | 定期采样 CPU/内存火焰图 |

---

## 3. 技术架构

```
                   OpenTelemetry Collector
                           ▲
                           │
                    OTLP 协议导出
                           │
             ┌─────────────┴─────────────┐
             │                           │
      TraceProvider                  MeterProvider
             │                           │
    ┌────────┴────────┐            ┌─────┴─────┐
    ▼        ▼        ▼            ▼           ▼
Agent    Tool      Memory       ToolCall    Token
Session  Registry  Manager      Counter     Counter
(Trace)  (Span)    (Span)       (Metric)    (Metric)
```

### 3.1 核心 Tracer 初始化

```python
# core/observability.py (新增)

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

_tracer: trace.Tracer | None = None

def init_tracer(
    service_name: str = "smallshrimp",
    otlp_endpoint: str | None = None,
    sample_rate: float = 1.0,
) -> trace.Tracer:
    """初始化 OpenTelemetry Tracer。"""
    global _tracer

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    # Console 导出器（调试用）
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)
    return _tracer

def get_tracer() -> trace.Tracer:
    """获取全局 Tracer。"""
    assert _tracer is not None, "call init_tracer() first"
    return _tracer
```

### 3.2 AgentSession 埋点

```python
# core/agent.py 中的 AgentSession.chat()

from ..core.observability import get_tracer

async def chat(self, message: str) -> str:
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "agent.chat",
        attributes={
            "agent.id": self.agent.agent_def.id,
            "session.id": self.session_id,
            "message.length": len(message),
        },
    ) as span:
        try:
            response = await self._chat_impl(message)
            span.set_attribute("response.length", len(response))
            span.set_status(trace.StatusCode.OK)
            return response
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            raise
```

### 3.3 ToolRegistry 埋点

```python
# tools/registry.py

async def execute_tool(self, name: str, **kwargs) -> str:
    tracer = get_tracer()
    # kwargs 脱敏：过滤 api_key/token/secret 等字段
    safe_args = _sanitize_args(kwargs)
    start = time.time()

    with tracer.start_as_current_span(
        f"tool.{name}",
        attributes={
            "tool.name": name,
            "tool.args": json.dumps(safe_args, ensure_ascii=False)[:500],
        },
    ) as span:
        try:
            result = await self._execute(name, **kwargs)
            span.set_attribute("tool.result_size", len(result))
            span.set_attribute("tool.duration_ms", (time.time() - start) * 1000)
            span.set_status(trace.StatusCode.OK)
            return result
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR, str(e))
            raise
```

### 3.4 LLMProvider 埋点

```python
# provider/llm/base.py

async def chat(self, messages, tools=None, reasoning_content=None):
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "llm.chat",
        attributes={
            "llm.model": self.config.model,
            "llm.provider": self.config.provider,
            "llm.tools_count": len(tools) if tools else 0,
        },
    ) as span:
        try:
            result = await self._chat(messages, tools, reasoning_content)
            usage = result.get("usage", {})
            span.set_attribute("llm.prompt_tokens", usage.get("prompt_tokens", 0))
            span.set_attribute("llm.completion_tokens", usage.get("completion_tokens", 0))
            span.set_attribute("llm.total_tokens", usage.get("total_tokens", 0))
            return result
        except Exception as e:
            span.record_exception(e)
            raise
```

### 3.5 参数脱敏

```python
SENSITIVE_KEYS = {"api_key", "token", "secret", "password", "authorization", "cookie"}

def _sanitize_args(args: dict) -> dict:
    """从工具参数中脱敏敏感字段。"""
    safe = {}
    for k, v in args.items():
        if any(s in k.lower() for s in SENSITIVE_KEYS):
            safe[k] = "***"
        elif isinstance(v, str) and len(v) > 1000:
            safe[k] = v[:200] + f"... ({len(v)} chars)"  # 大内容截断
        else:
            safe[k] = v
    return safe
```

---

## 4. 结构化日志（V1）

### JSON 日志格式

当前非结构化 `logger.info(msg)` → 目标结构化：

```python
# 使用 structlog 或 Python 内置的 JSON 日志
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

log = structlog.get_logger()
log.info("tool_executed", tool="read", path="/tmp/x.py", duration_ms=12)
# 输出: {"event": "tool_executed", "tool": "read", "path": "/tmp/x.py", "duration_ms": 12, "level": "info", "timestamp": "2026-06-25T12:00:00Z"}
```

---

## 5. 配置项

```yaml
# config.user.yaml
observability:
  enabled: false
  tracer:
    service_name: smallshrimp
    otlp_endpoint: ""              # 如 http://localhost:4317
    sample_rate: 1.0               # 采样率 0.0~1.0
  logging:
    format: json                   # json / console（默认 console）
    level: info
    otlp_endpoint: ""
```

---

## 6. 测试要点

| 场景 | 说明 |
|------|------|
| tracer 初始化 | `init_tracer()` 后 `get_tracer()` 返回非 None |
| AgentSession 追踪 | chat() 调用产生一个 trace，含 response 属性 |
| 工具调用 span | 每个工具调用产生一个子 span，含 duration、args(脱敏) |
| 脱敏 | api_key 等敏感字段在 span attributes 中被替换为 "***" |
| 可禁用 | `observability.enabled: false` 时不产生 OTel 调用 |
| 性能影响 | span 创建开销 < 1ms，不对 Agent 循环产生显著影响 |

---

## 7. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | OTel 初始化 + AgentSession trace + ToolRegistry span + LLM span | 3d |
| P0+ | 参数脱敏 + 可禁用开关 + Console 导出 | 1d |
| P1 | 结构化日志 + Prometheus metrics | 2d |
| P2 | 健康检查端点 + Grafana 模板 + Profiling | 2d |

---

## 8. 风险 & 缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| OTel 依赖导致包体积增大 | pip install 更慢 | 标记为可选 extra `[observability]` |
| span 创建开销累积 | 高频工具调用时性能下降 | 批量处理器 + 采样率控制 |
| 敏感信息泄露到 span | API Key 等暴露 | 强制脱敏 + reviewer 审核 |
| OTel 依赖版本冲突 | 与 litellm 等已有依赖冲突 | 严格版本上界 |

---

## 9. 附录

### 9.1 依赖变更

| 依赖 | 说明 |
|------|------|
| `opentelemetry-api>=1.20,<2` | 基础 API |
| `opentelemetry-sdk>=1.20,<2` | SDK 实现 |
| `opentelemetry-exporter-otlp-proto-grpc>=1.20,<2` | OTLP gRPC 导出 |
| `opentelemetry-instrumentation-httpx>=0.40,<1` | HTTP 客户端追踪（V1） |
| `structlog>=24.0,<25` | 结构化日志（V1） |

### 9.2 变更文件

| 文件 | 变更类型 |
|------|----------|
| `src/SmallShrimp/core/observability.py` | 新增 — Tracer 初始化 + 工具函数 |
| `src/SmallShrimp/core/agent.py` | 修改 — AgentSession.chat() 埋点 |
| `src/SmallShrimp/tools/registry.py` | 修改 — execute_tool span |
| `src/SmallShrimp/provider/llm/base.py` | 修改 — LLM chat span |
| `pyproject.toml` | 修改 — 新增 `[observability]` 可选依赖 |

### 9.3 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始草案 |
