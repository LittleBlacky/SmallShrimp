---
id: skill-creator
name: skill-creator
description: 创建或更新 SmallShrimp 技能。用于设计、打包具有脚本、参考资料和资源文件的技能模块。
---

# Skill Creator

本指南帮助你在 SmallShrimp 项目中创建有效的技能（Skill）。

## 什么是 Skill

Skill 是模块化、自包含的包，通过提供专业知识、工作流程和工具来扩展 Agent 的能力。可以把它看作是特定领域或任务的"入职指南"——将通用 Agent 转化为配备程序性知识的专用 Agent。

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
    └── assets/        - 资源文件
```

### SKILL.md 格式

```markdown
---
id: skill-id
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
- `description**：这是主要的触发机制，帮助 Agent 理解何时使用该技能
  - 同时包含技能功能和使用场景
  - 所有"何时使用"信息放这里，正文只在触发后加载

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

Skill 应该只包含直接支持其功能的必要文件。**不要创建**额外文档：
- README.md
- INSTALLATION_GUIDE.md
- CHANGELOG.md
- 等

## Skill 创建流程

### 1. 理解技能的使用场景

通过具体示例理解技能将如何被使用：
- "这个技能支持什么功能？"
- "能给出一些使用示例吗？"
- "用户说什么应该触发这个技能？"

### 2. 规划可复用内容

分析每个示例：
1. 如何从零开始执行
2. 重复执行时需要哪些脚本、参考资料和资源

### 3. 初始化 Skill

创建技能目录结构：
```bash
mkdir -p workspace/skills/{skill-name}
```

### 4. 编辑 SKILL.md

#### frontmatter

```markdown
---
id: my-skill
name: my-skill
description: 技能描述，包含触发场景
---
```

#### 正文

编写使用技能及其打包资源的说明。

### 5. 迭代

基于实际使用情况进行改进。

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
- [ ] 有具体的使用示例
- [ ] 有前提条件和限制说明
- [ ] 命名符合规范（kebab-case）
- [ ] 没有包含不必要的额外文档文件