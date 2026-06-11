# SmallShrimp 记忆架构 v2

> 基于 OpenClaw 设计哲学 + HRR 实验数据 + 现有 Provider 架构的重构方案。

---

## 核心原则

1. **文件是真相源** — 所有记忆以 Markdown 文件存储，用户可直接编辑、Git 管理
2. **SQLite 仅做索引** — 加速检索，索引丢了不影响记忆本身
3. **本地优先** — 不依赖任何云端服务
4. **文件平铺** — 5 个文件/目录平铺，职责单一，无嵌套

---

## 文件结构

所有记忆文件平铺在 `memories/` 下，无嵌套目录。每个文件职责单一。

```
workspace/memories/
├── profile.md              # 用户档案（身份、长期偏好）
├── facts.md                # 知识（技术事实、工具用法、约定）
├── projects.md             # 项目上下文（端口、路径、命令）
├── reflections.md          # 经验教训（踩坑记录、行为修正）
└── daily/                  # 每日日志（会话摘要、待办）
    ├── 2026-06-10.md
    ├── 2026-06-11.md
    └── ...
```

### profile.md — 用户档案

最高优先级，主会话自动加载（~500 chars），群聊/共享场景不注入。

```markdown
# 用户档案
- 姓名：Zane
- 主力语言：Python
- 编辑器：VS Code
- 主题：深色模式
- 沟通：中文、简洁直接、给代码示例
- 重视：代码质量、测试覆盖、自动化
```

### facts.md — 知识

按需检索，不自动加载。存储跨会话的技术事实。

```markdown
# 事实

## Python 生态
- Python 版本要求 >= 3.11
- 依赖管理用 pip + requirements.txt
- 项目使用 pytest 运行测试
- 测试覆盖率目标 80% 以上

## 框架与库
- Web 框架用 FastAPI
- ORM 用 SQLAlchemy
- 日志记录使用 loguru
```

### projects.md — 项目上下文

按需检索，不自动加载。每个项目一个分段。

```markdown
# 项目上下文

## SmallShrimp
- 根目录: g:/agent/SmallShrimp
- Python 3.11
- 虚拟环境: .venv/
- 端口: 8000
- 安装: pip install -e .
- 测试: pytest
```

### reflections.md — 经验教训

按需检索，但**优先级高于 facts**。由 FailureLearner 自动写入，不经过 LLM。

```markdown
# 经验教训

## 文件操作
- read_file 前应先确认路径存在
- 写文件指定 encoding='utf-8'

## 命令行
- shell 命令失败后检查退出码
- 不要忽略 stderr 输出
- Docker build 前检查 Dockerfile 语法

## Git
- git merge 冲突手动解决而非 force push
- 提交前运行 pytest
```

### daily/ — 每日日志

替代 sessions 层。当天+前一天自动加载到工作记忆。

```markdown
# 2026-06-11 日志

## 会话摘要
- 讨论了 OpenClaw 记忆架构设计
- 确认新方案：文件真相源 + SQLite 索引 + HRR 检索

## 完成事项
- HRR 向量召回实验：keyword 36% → HRR 43% → +LLM 51%

## 待办
- [ ] 实现 Markdown 文件存储层
- [ ] 迁移现有 SQLite 数据到文件
```

---

## 文件层级定义

| 文件 | 存什么 | 写入方式 | 加载方式 | token |
|-----|--------|---------|---------|-------|
| **profile.md** | 身份、长期偏好、固定规则 | LLM 提取 / 用户直接编辑 | 每轮自动注入 | ~500 |
| **facts.md** | 技术事实、工具用法 | LLM 提取 / 用户直接编辑 | 按需检索 | ~500 |
| **projects.md** | 项目上下文（路径、端口、命令） | LLM 提取 / 用户直接编辑 | 按需检索 | ~500 |
| **reflections.md** | 踩坑教训、行为修正 | **FailureLearner 自动写** | 按需检索，优先级高 | ~500 |
| **daily/** | 会话摘要、待办 | sync_turn 自动写 | 当天+前一天自动加载 | ~500 |

---

## 检索架构

```
用户输入
    │
    ▼
┌─────────────────────────────┐
│  检索触发器                  │
│  - 当前问题是否需要知识？     │
│  - 是否涉及过往项目？        │
│  - LLM 自主调 recall 工具    │
└──────────┬──────────────────┘
           │需要检索
           ▼
┌─────────────────────────────┐
│  双路检索                    │
│  ┌──────────┐ ┌──────────┐  │
│  │ FTS5     │ │ HRR      │  │
│  │ 关键词    │ │ 语义      │  │
│  │ 精准匹配  │ │ 模糊匹配  │  │
│  └────┬─────┘ └────┬─────┘  │
│       │            │        │
│       ▼            ▼        │
│     合并 → MMR重排序 → top-5│
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  读取对应 .md 文件全文        │
│  注入 user message 尾部      │
└─────────────────────────────┘
```

### 检索参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| FTS5 权重 | 0.4 | 关键词精准匹配 |
| HRR 权重 | 0.4 | 语义模糊匹配 |
| 时间衰减权重 | 0.2 | 每天衰减，30 天半衰期 |
| MMR λ | 0.7 | 相关性 vs 多样性平衡 |
| Top-K | 5 | 最终注入条数 |

### SQLite 索引表结构

```sql
CREATE TABLE memory_index (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT NOT NULL,       -- 对应 .md 文件路径
    section     TEXT NOT NULL,       -- 段落/块标识
    content     TEXT NOT NULL,       -- 索引文本
    layer       TEXT NOT NULL,       -- profile/facts/projects/reflections/daily
    mtime       INTEGER NOT NULL,    -- 文件修改时间
    hash        TEXT NOT NULL,       -- 内容 SHA-256
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE memory_fts USING fts5(content, content=memory_index, content_rowid=id);
-- HRR 向量存 BLOB 列或 vec0 虚拟表
```

### 增量索引

检测 `mtime` + `hash`，仅在文件变化时重新索引对应条目，不做全量重建。

---

## 记忆写入管线

```
Turn End
    │
    ▼
┌──────────────────────────────┐
│  LLM 记忆提取                 │
│  prompt: 从本轮对话提取需要    │
│  长期保存的核心信息            │
│  分类: 用户偏好/技术事实/      │
│        项目上下文/经验教训/    │
│        待办事项               │
└───────────┬──────────────────┘
            │
            ▼
┌──────────────────────────────┐
│  Correction Detection        │
│  (用户明确纠正 → 写 profile)  │
│                              │
│  FailureLearner              │
│  (工具报错 → 写 knowledge)    │
└───────────┬──────────────────┘
            │
            ▼
┌──────────────────────────────┐
│  写 .md 文件                  │
│  - 追加/更新对应段落          │
│  - 去重检查（内容不重复写入）  │
│  - 格式标准化                │
└───────────┬──────────────────┘
            │
            ▼
┌──────────────────────────────┐
│  增量索引更新                 │
│  - 重新索引修改的文件          │
│  - 更新 mtime + hash         │
│  - 重新计算 HRR 向量          │
└──────────────────────────────┘
```

---

## 实现路线

### Step 1: Markdown 存储层

- 修改 `BuiltinProvider.store()`：写 SQLite → 写 .md 文件
- SQLite 保持为索引（FTS5）
- 保留 `store()` 签名不变，上层调用不受影响

### Step 2: 检索升级

- FTS5 全文检索（现有 SQLite 能力）
- HRR 向量检索（实验已验证，43%）
- 双路融合 + MMR 重排序
- 时间衰减因子

### Step 3: 写入管线

- LLM post-turn extraction prompt（参考 OpenClaw 模板）
- Correction Detection + FailureLearner 接入文件写入
- 去重检查

### Step 4: 清理

- 去掉 sessions 层，改为 daily/ 目录
- 迁移现有数据
- 更新 MemoryProvider ABC 接口说明

---

## 对比

| 维度 | v1（当前） | v2（方案） |
|------|-----------|-----------|
| 真相源 | SQLite 二进制 | **Markdown 文件** |
| 用户可编辑 | ❌ | **✅ 编辑器直接改** |
| 检索 | 关键词 | **FTS5 + HRR 混合** |
| 时间衰减 | ❌ | ✅ |
| MMR 重排序 | ❌ | ✅ |
| 分层 | 5 层（含 sessions） | **3 层** |
| 增量索引 | ❌ | ✅ |
| 实验验证 | — | HRR 43%, +LLM 51% |
