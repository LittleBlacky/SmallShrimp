# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SmallShrimp 是一个可多端响应、持续进化的个人助理 Agent（Python 3.11+）。它的主场是用户的电脑：文件、文档、表格、幻灯片、代码项目、消息、日程和日常习惯。产品目标分四阶段：第一阶段协助用户完成任务；第二阶段理解用户任务场景、画像和偏好，沉淀方法论并近似成为用户克隆；第三阶段在近似替代用户后持续自我进化，变得更高效、更实用、更正确；第四阶段将进化结果反馈给用户，帮助用户提升。底层工程采用 harness engineering 思路，通过上下文、工具、权限、记忆、观测和反馈闭环增强模型能力。版本 0.2.0，使用 hatchling 构建。

## Commands

```bash
# 安装（开发模式）
pip install -e .

# 安装可选依赖
pip install -e ".[memory,vector,telegram,discord,benchmark]"

# CLI 入口
smallshrimp init          # 初始化工作区
smallshrimp chat          # 交互式聊天
smallshrimp chat --port 8000  # 启动完整服务（CLI + 渠道 + WebSocket + 定时任务）
smallshrimp version

# 测试
pytest                           # 全部测试
pytest tests/test_memory.py      # 单个测试文件
pytest -k "test_name"            # 按名称过滤

# 构建
python -m build
```

## Architecture

### Event-Driven Core

所有组件通过 `EventBus`（异步 pub/sub）通信，数据流：

```
外部输入 → InboundEvent → AgentWorker → AgentSession.chat() → OutboundEvent → DeliveryWorker → 渠道输出
```

关键事件类型在 `core/events.py`：`InboundEvent`、`OutboundEvent`、`DispatchEvent`、`DispatchResultEvent`。

### Agent System

- **Agent 定义**：`workspace/agents/<name>/AGENT.md`（YAML frontmatter + markdown 正文作为系统提示词），可选 `SOUL.md`（人格层）
- **Agent 加载**：`core/agent_loader.py` 的 `AgentLoader` 扫描 agents 目录
- **Agent 路由**：`core/routing.py` 的 `RoutingTable`，通过正则绑定将事件源映射到 Agent，优先级：精确 > 正则 > 通配符
- **Agent 核心循环**：`core/agent.py` 的 `AgentSession.chat()` — MCP 懒初始化 → 纠错检测 → 信任对话 → 主循环（ContextGuard 压缩 → 构建消息 → 调用 LLM → 执行工具） → 失败学习 → 历史持久化 → 记忆同步

### Tool System

- **注册中心**：`tools/registry.py` 的 `ToolRegistry`
- **工具基类**：`tools/base.py` 的 `Tool` ABC，`@tool` 装饰器（`tools/decorators.py`）自动从函数签名提取 JSON Schema
- **只读工具并行执行**：`read`、`glob`、`grep`、`websearch`、`webread`、`skill` 通过 `asyncio.gather` 并行
- **写工具串行执行**：经过权限检查后逐个执行
- **MCP 工具**：`core/mcp.py` 支持 stdio/SSE 传输，自动发现注册为 `mcp__<server>__<tool>`

### Memory System（`core/memory/`）

5 层声明式记忆，每层有独立的注入策略和搜索行为：

| 层 | 用途 | 注入方式 | 重要性 |
|---|---|---|---|
| profile | 用户画像 | session 冻结 | 10 |
| facts | 技术事实 | 按需搜索 | 5 |
| projects | 项目上下文 | 按需搜索 | 6 |
| reflections | 反思教训 | 每轮自动预取 | 6 |
| constraints | 硬性约束 | session 永不压缩 | 10 |

**写入管线**：`SignalDetector`（纠错 0.9 / 失败 0.8 / 重复 0.7 / 关键词 0.5 / LLM 工具 0.3） → `ConfidenceGate`（≥0.7 直写 / ≥0.4 暂存 / <0.4 丢弃） → `StagingArea`（出现 ≥2 次晋升）

**存储**：Markdown 文件 + SQLite FTS5（jieba 中文分词）+ 可选 sqlite-vec 向量搜索，混合检索含 MMR 重排序

**辅助系统**：`DreamingEngine`（离线记忆整合）、`ReflectionEngine`（重要性触发反思）、`FailureLearner`（跨轮次失败模式）

### Context Management（4 级压缩）

`core/context_guard.py` 的 `ContextGuard`：

1. **Budget**：大结果头尾截断（30K/15K 字符）
2. **Snip**：>60% 上下文满时替换过期工具结果为占位符
3. **Microcompact**：60s 空闲后清理旧工具结果
4. **Autocompact**：LLM 总结对话历史

配合：`ConversationBuffer`（8 轮滑动窗口 / 12 轮触发摘要）、`TopicSegmenter`（话题分段）、`PriorityResolver`（信息源冲突解决）、`TodoTracker`（任务进度追踪）

### Prompt Builder（`core/prompt_builder.py`）

3 段缓存策略优化 LLM prefix cache：

- **永久缓存**（进程级，字节稳定）：L1 Identity（AGENT.md） → L2 Soul（SOUL.md） → L3 Bootstrap（BOOTSTRAP.md + AGENTS.md）
- **冻结段**（会话级）：L5 用户画像
- **可变段**（每轮）：L4 渠道提示

### Security（7 层防御）

`TrustDialog` → `PermissionMode`（5 种模式） → `WorkspaceBoundary` → `ShellAST`（tree-sitter） → `ToolGuardrails` → `Sandbox`（Python/OS/Docker 3 级） → `UserConfirmation`

### Server（`server/`）

- **Context**（`server/context.py`）：DI 容器，持有所有依赖
- **Server**（`server/server.py`）：编排 Worker（AgentWorker / DeliveryWorker / CronWorker / ChannelWorker / WebSocketWorker），Worker 崩溃自动重启
- **FastAPI**（`server/app.py`）：WebSocket 聊天 + REST API + WeCom 回调

### LLM Provider（`provider/llm/`）

基于 `litellm` 的统一接口，`ThinkingStrategy` 模式处理不同提供商的思考/推理模式（DeepSeek / Anthropic / Gemini / NoOp）。

## Key Patterns

- **声明式配置**：Agent（AGENT.md）、Skill（SKILL.md）、Cron（CRON.md）均使用 YAML frontmatter + markdown
- **配置热重载**：Watchdog 监听文件变更，级联更新 LLM provider / 权限 / MCP
- **优雅降级**：Web 搜索多 provider fallback 链；向量搜索降级为纯 FTS5；Embedding 降级为字符 n-gram

## Reference Projects

仓库中包含多个参考/学习项目（非 SmallShrimp 核心代码）：

- `references/external-agents/hermes-agent/` — 生产级自改进 Agent 平台（多平台网关、技能系统、轨迹压缩）
- `references/tutorials/claude-code-from-scratch/` — Claude Code 架构的教育性复现（TypeScript + Python）
- `references/tutorials/build-your-own-openclaw/` — 18 步渐进式 Agent 教程
- `references/knowledge-apps/Comet/` — 多用户知识库 + 记忆助手（Neo4j 知识图谱、深度研究管线）
- `references/external-agents/ZLAgent/` — IM 优先个人助手（三层架构、GraphRAG、意图优先管线）
- `references/external-agents/deer-flow/` — 多 Agent 工作流与技能系统参考

## Repository Layout

- `src/SmallShrimp/` — Python 主包，包含 core、tools、provider、channels、server、cli、utils。
- `tests/` — pytest 测试，按功能平铺命名。
- `docs/` — SmallShrimp 与桌面端设计文档。
- `apps/desktop/` — Electron 桌面端，不与 Python 主包混放。
- `examples/default_workspace/` — 示例工作区配置。
- `workspace/` — 本地运行时工作区，避免提交用户配置、会话、记忆和缓存。
- `references/` — 外部参考项目，按教程、外部 Agent、知识应用分组。
- `assets/` — 截图和静态资源。
