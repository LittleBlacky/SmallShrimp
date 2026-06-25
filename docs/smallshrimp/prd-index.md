# SmallShrimp 框架 — 产品需求文档索引

> 最后更新: 2026-06-25

本文档索引了 SmallShrimp 核心框架当前规划的所有 PRD（产品需求文档）。每个 PRD 对应一个独立的优化方向，按优先级排序。

---

## 优先级矩阵

| 优先级 | 方向 | 影响面 | 工作量 | 文档 |
|--------|------|--------|--------|------|
| ⭐⭐⭐⭐⭐ | ① grep 工具增强 | Tools | 小 | [PRD](features/01-grep-enhancement/PRD.md) |
| ⭐⭐⭐⭐⭐ | ② EventBus 初始化鲁棒性 | Core | 小 | [PRD](features/02-eventbus-init/PRD.md) |
| ⭐⭐⭐⭐ | ③ write 工具原子写入 | Tools | 极小 | [PRD](features/03-write-atomicity/PRD.md) |
| ⭐⭐⭐⭐ | ④ 工具入参校验 | Tools | 中 | [PRD](features/04-tool-input-validation/PRD.md) |
| ⭐⭐⭐⭐ | ⑤ 记忆向量检索增强 | Memory | 中 | [PRD](features/05-memory-vector-search/PRD.md) |
| ⭐⭐⭐ | ⑥ PromptBuilder 缓存自动失效 | Core | 中 | [PRD](features/06-prompt-cache-invalidation/PRD.md) |
| ⭐⭐⭐ | ⑦ 多 Agent 路由增强 | Core | 中-大 | [PRD](features/07-agent-routing/PRD.md) |
| ⭐⭐ | ⑧ Worker DAG 编排 | Server | 大 | [PRD](features/08-worker-dag/PRD.md) |
| ⭐⭐ | ⑨ 记忆推理系统 | Memory | 大 | [PRD](features/09-memory-reasoning/PRD.md) |
| ⭐⭐ | ⑩ 可观测性 | Core/Server | 大 | [PRD](features/10-observability/PRD.md) |

---

## 目录结构

```
docs/smallshrimp/
├── prd-index.md                        # ← 当前文件
├── features/
│   ├── 01-grep-enhancement/
│   │   └── PRD.md                      # grep 工具增强
│   ├── 02-eventbus-init/
│   │   └── PRD.md                      # EventBus 初始化鲁棒性
│   ├── 03-write-atomicity/
│   │   └── PRD.md                      # write 工具原子写入
│   ├── 04-tool-input-validation/
│   │   └── PRD.md                      # 工具入参校验
│   ├── 05-memory-vector-search/
│   │   └── PRD.md                      # 记忆向量检索增强
│   ├── 06-prompt-cache-invalidation/
│   │   └── PRD.md                      # PromptBuilder 缓存自动失效
│   ├── 07-agent-routing/
│   │   └── PRD.md                      # 多 Agent 路由增强
│   ├── 08-worker-dag/
│   │   └── PRD.md                      # Worker DAG 编排
│   ├── 09-memory-reasoning/
│   │   └── PRD.md                      # 记忆推理系统
│   └── 10-observability/
│       └── PRD.md                      # 可观测性
```

---

## 快速浏览

### 短期（P0 — 高价值、低风险）

| PRD | 一句话 |
|-----|--------|
| [01-grep](features/01-grep-enhancement/PRD.md) | 将纯 Python 字符串匹配升级为支持正则、glob、上下文行的 grep，可选 ripgrep 后端 |
| [02-eventbus](features/02-eventbus-init/PRD.md) | 消除 `try/except RuntimeError` 降级模式，建立两阶段初始化生命周期 |
| [03-write](features/03-write-atomicity/PRD.md) | 临时文件 → `os.replace()` 原子写入，防止写入中断导致目标文件损坏 |

### 中期（P1 — 架构级改进）

| PRD | 一句话 |
|-----|--------|
| [04-tool-validation](features/04-tool-input-validation/PRD.md) | 在 Registry 层用 Pydantic model 做统一入参校验，自动推导 LLM Schema |
| [05-memory-vector](features/05-memory-vector-search/PRD.md) | 用 sentence-transformers + sqlite-vec 为记忆系统添加语义向量检索 |
| [06-prompt-cache](features/06-prompt-cache-invalidation/PRD.md) | 用文件 mtime 跟踪实现 PromptBuilder 三段缓存的自动失效 |

### 长期（P2 — 新能力扩展）

| PRD | 一句话 |
|-----|--------|
| [07-routing](features/07-agent-routing/PRD.md) | LLM + 关键词双路由 + 健康检查 + 路由表 YAML 配置 |
| [08-worker-dag](features/08-worker-dag/PRD.md) | Worker 从线性列表升级为 DAG 编排（拓扑排序 + 依赖管理）|
| [09-memory-reasoning](features/09-memory-reasoning/PRD.md) | 矛盾检测 + 时间衰减 + 推理引擎 |
| [10-observability](features/10-observability/PRD.md) | OpenTelemetry 追踪 + 结构化日志 |

---

## 各 PRD 已覆盖的内容

| 维度 | 覆盖情况 |
|------|----------|
| 产品定位与价值 | 全部包含「产品定位」和「核心价值」表 |
| 功能范围（MVP/V1/V2） | 全部按 P0/P1/P2 分层定义 |
| 技术架构 | 全部包含架构图或伪代码 |
| 实现设计 | 关键模块包含「当前值 vs 目标值」代码对比 |
| 测试要点 | 每个 PRD 含 5+ 测试场景 |
| 风险 & 缓解 | 每个 PRD 含风险表 |
| 变更文件清单 | 每个 PRD 附录含变更文件列表 |

---

## 总工作量估算

| 阶段 | PRD 数量 | 预估总工期 |
|------|----------|-----------|
| P0 | 4 (01-04) | ~6 人日 |
| P1 | 3 (05-07) | ~9 人日 |
| P2 | 3 (08-10) | ~10 人日 |
| **总计** | **10** | **~25 人日** |
