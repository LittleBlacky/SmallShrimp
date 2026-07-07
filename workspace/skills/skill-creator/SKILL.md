---
id: skill-creator
name: skill-creator
description: 创建或更新 SmallShrimp 技能。用于设计、打包具有脚本、参考资料和资源文件的技能模块。
origin: bundled
status: active
version: 1.0.0
---

# Skill Creator

本指南帮助你在 SmallShrimp 项目中创建、更新、评估和迭代有效的技能（Skill）。

核心循环：

1. 捕捉用户想沉淀的任务方法。
2. 写出一个简洁的 `SKILL.md` 草稿。
3. 用真实任务提示测试它是否会被正确触发、是否真的提高结果质量。
4. 根据用户反馈和测试结果改进 skill。
5. 反复迭代，直到 skill 足够稳定。
6. 必要时优化 `description`，让它在正确场景更容易被触发。

## 什么是 Skill

Skill 是模块化、自包含的 Markdown-first 能力包，通过提供专业知识、工作流程和工具来扩展 Agent 的能力。可以把它看作是特定领域或任务的"入职指南"——将通用 Agent 转化为配备程序性知识的专用 Agent。

SmallShrimp 的 Skill 规范应兼容主流 skill package 约定，不发明独立标准：

- `SKILL.md` 是唯一必需入口
- YAML frontmatter 只强制 `name` 和 `description`
- `id`、`origin`、`status`、`version`、`triggers` 等是 SmallShrimp 可理解的可选扩展
- `scripts/`、`references/`、`assets/`、`tests/` 是可选附加资源
- `skill.yaml`、`usage.json`、`versions/` 是系统管理层的可选文件，不应成为用户手写 skill 的负担

### Skill 能提供什么

1. **专业工作流** - 特定领域的多步骤流程
2. **工具集成** - 处理特定文件格式或 API 的说明
3. **领域知识** - 公司专业知识、数据模式、业务逻辑
4. **打包资源** - 复杂重复任务的脚本、参考资料和资源文件

## 核心原则

### 简洁为王

上下文窗口是公共资源。Skill 与系统提示、对话历史、其他 Skill 元数据以及实际用户请求共享上下文。

**默认假设：Agent 已经非常智能。** 只添加 Agent 没有的上下文。审视每一条信息："Agent 真的需要这个解释吗？"

用简洁的示例代替冗长的解释。

### 适当的自由度

根据任务的脆弱性和可变性匹配具体程度：

- **高自由度（文本指令）**：多种方法有效、决策依赖上下文、需要启发式引导的场景
- **中自由度（伪代码/带参数脚本）**：存在首选模式、允许一定变化、配置影响行为的场景
- **低自由度（特定脚本、少量参数）**：操作容易出错、一致性关键、必须遵循特定顺序的场景

### 渐进式披露设计

Skill 使用三层加载系统管理上下文：

1. **元数据（name + description）** - 始终在上下文（~100 字）
2. **SKILL.md 正文** - Skill 触发时加载（<5k 字）
3. **打包资源** - Agent 需要时加载（无限制）

## Skill 结构

```
skill-name/
├── SKILL.md（必需）
│   ├── YAML frontmatter 元数据
│   │   ├── name:（必需）
│   │   └── description:（必需）
│   └── Markdown 正文（必需）
└── 打包资源（可选）
    ├── scripts/       - 可执行脚本
    ├── references/    - 参考文档
    ├── assets/        - 资源文件
    └── tests/         - 示例或验证用例
```

### SKILL.md 格式

```markdown
---
name: Skill Name
description: 一句话描述技能功能和触发场景
---

# 标题

## 概述
这个技能做什么，为什么有用。

## 前提条件
- 需要什么配置
- 依赖哪些工具

## 使用方法
具体的使用步骤。

## 代码示例
关键代码片段。

## 最佳实践
- 建议 1
- 建议 2
```

### frontmatter 编写要点

- `name`：Skill 名称
- `description`：这是主要的触发机制，帮助 Agent 理解何时使用该技能
  - 同时包含技能功能和使用场景
  - 所有"何时使用"信息放这里，正文只在触发后加载
- `id`：可选，未提供时可用目录名作为稳定标识
- `triggers`：可选，用于补充关键词匹配；不能替代 `description`
- `origin/status/version/risk_level`：可选，供 SmallShrimp 的演化、治理和风险控制使用

### 打包资源

#### `scripts/` - 可执行脚本

用于需要确定性可靠性的任务或被反复重写的代码。

**何时包含**：当相同代码被反复重写或需要确定性可靠性时

#### `references/` - 参考文档

在需要时加载到上下文中供 Agent 参考的文档。

**何时包含**：Agent 在工作时应该参考的文档（如数据库 schema、API 文档、公司政策）

**最佳实践**：如果文件很大（>10k 字），在 SKILL.md 中包含 grep 搜索模式

#### `assets/` - 资源文件

不加载到上下文中，而是在 Agent 产生的输出中使用的文件。

**何时包含**：技能需要在最终输出中使用的文件（如模板、图片、图标）

### 不应包含的内容

Skill 应该只包含直接支持其功能的必要文件。不要为了显得完整而创建无用文档。`CHANGELOG.md`、`versions/`、`usage.json` 只有在确实需要版本管理或系统治理时才添加。

## Skill 创建流程

### 1. 捕捉意图

先从当前对话和已有任务记录里提取信息，不要重复问用户已经说过的内容。

需要明确：

1. 这个 skill 要让 SmallShrimp 学会做什么。
2. 哪些用户表达、文件类型、任务场景应该触发它。
3. 期望输出是什么格式。
4. 这个 skill 是否适合测试。

可客观验证的任务，例如文件转换、数据抽取、代码生成、固定流程执行，应该优先设计测试用例。偏主观的任务，例如写作风格、审美判断、创意表达，可以以用户反馈为主。

### 2. 访谈和补充研究

围绕边界条件、输入输出、示例文件、成功标准和依赖工具继续追问。

如果用户已经给了足够上下文，直接进入草稿，不要为了流程感强行提问。

需要参考外部规范、已有同类 skill 或项目约定时，先查资料，再写 skill。目标是减少用户解释成本。

### 3. 规划可复用内容

分析每个使用场景：

1. 从零开始如何完成。
2. 哪些步骤是重复、脆弱或容易写错的。
3. 哪些内容应该进入 `SKILL.md`。
4. 哪些内容应该拆到 `scripts/`、`references/`、`assets/` 或 `tests/`。

如果多个测试任务里都会重复写同一段脚本，应该把脚本沉淀到 `scripts/`，再在 `SKILL.md` 里说明何时使用它。

### 4. 初始化 Skill

创建技能目录结构：
```bash
mkdir -p workspace/skills/{skill-name}
```

### 5. 编辑 SKILL.md

#### frontmatter

```markdown
---
name: my-skill
description: 技能描述，包含触发场景
---
```

#### 正文

编写使用技能及其打包资源的说明。

正文建议包含：

1. 这个 skill 解决什么问题。
2. 什么时候使用它。
3. 使用前要收集什么上下文。
4. 推荐执行步骤。
5. 必要的输出格式。
6. 常见错误和边界情况。
7. 需要读取的参考文件或调用的脚本。

优先解释“为什么这样做”，不要堆砌生硬的绝对规则。只有在安全、格式或协议确实不可违反时，才使用强约束。

### 6. 设计测试提示

写完草稿后，准备 2-3 个真实用户会说的测试提示。

测试提示应该具体、有上下文，避免过于抽象：

- 差：`总结这个文档`
- 好：`把 downloads 里的 Q4 会议纪要整理成老板能直接看的中文要点，保留待办负责人和截止日期`

测试提示应覆盖：

1. 明确应该触发该 skill 的场景。
2. 容易误触发的相邻场景。
3. 用户表达不完整但意图明显的场景。

如果 skill 适合结构化验证，可以把测试写入 `tests/` 或 `evals/evals.json`。如果不适合自动验证，就记录人工评审标准。

### 7. 运行、评估和改进

运行测试时尽量比较：

1. 使用 skill 的结果。
2. 不使用 skill 或使用旧版本 skill 的结果。
3. 用户反馈。
4. 是否节省步骤、减少错误、提高一致性。

评估时重点看：

1. skill 是否在正确场景触发。
2. 输出是否符合用户期望。
3. 是否遗漏关键步骤。
4. 是否让 agent 做了多余工作。
5. 是否有内容可以下沉成脚本、参考资料或模板。

### 8. 迭代

基于实际使用情况进行改进。

改进原则：

1. 从反馈中抽象通用方法，不要只为某个样例过拟合。
2. 删除没有贡献的说明，保持 `SKILL.md` 精简。
3. 把重复性、确定性强的操作沉淀为脚本。
4. 把长参考资料放入 `references/`，不要塞满正文。
5. 更新后再次测试。

### 9. 优化 description

`description` 是 skill 的主要触发机制。创建或大幅修改 skill 后，应检查它是否足够清楚地说明：

1. skill 做什么。
2. 什么时候应该使用。
3. 哪些相关表达也应该触发。
4. 哪些相邻任务不该触发。

description 可以适当“积极”一点，让系统在合适场景更愿意加载它，但不能夸大能力或诱导误触发。

### 10. 打包和交付

当 skill 稳定后：

1. 确认 `SKILL.md` 是唯一必需入口。
2. 确认资源路径都使用相对路径。
3. 确认没有无用文档或临时文件。
4. 确认用户能理解 skill 的用途和边界。
5. 如有版本管理需求，再补充 `CHANGELOG.md` 或 `versions/`。

## SmallShrimp 特定说明

### 技能文件位置

```
workspace/skills/{skill-name}/
└── SKILL.md
```

### 可用工具

技能可以调用内置工具：
- 文件操作：`read`, `write`, `glob`, `grep`
- Web 操作：`websearch`, `webread`
- 定时任务：`CronCreate`, `CronList`, `CronDelete`

### 事件系统集成

```python
from src.SmallShrimp.core.eventbus import EventBus
from src.SmallShrimp.core.events import OutboundEvent

# 订阅事件
eventbus.subscribe(OutboundEvent, handle_response)

# 发布事件
await eventbus.publish(OutboundEvent(session_id="xxx", content="result"))
```

## 最佳实践

1. **单一职责** - 每个 Skill 聚焦一个能力
2. **自包含** - 尽量减少外部依赖
3. **可测试** - 考虑提供测试用例
4. **有示例** - 包含具体的使用示例
5. **渐进式** - 使用 references/ 目录管理大量内容
6. **简洁** - 正文控制在 500 行以内

## 创建检查清单

- [ ] 有清晰的功能描述和触发场景
- [ ] frontmatter 包含 name 和 description
- [ ] 没有强制用户填写 SmallShrimp 专属扩展字段
- [ ] description 足够说明何时触发，而不是只写功能名
- [ ] 有具体的使用示例
- [ ] 有前提条件和限制说明
- [ ] 有 2-3 个真实测试提示，或说明为什么不适合测试
- [ ] 重复、确定、容易出错的步骤已考虑沉淀到 scripts/
- [ ] 长参考资料已考虑放入 references/
- [ ] 命名符合规范（kebab-case）
- [ ] 没有包含不必要的额外文档文件
