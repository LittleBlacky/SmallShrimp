# grep 工具增强 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 涉及层: Tools

---

## 1. 产品概述

### 1.1 产品定位

将 `tools/builtin_tools.py` 中的纯 Python 字符串匹配 `grep` 工具升级为支持正则表达式、多文件过滤、递归深度控制和上下文行显示的高性能全文搜索工具。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| 仅支持纯字符串包含匹配 (`if pattern in content`)，不支持正则 | 支持 `re` 正则搜索，LLM 可精确匹配变量名、函数签名 |
| 逐文件扫描，无递归深度控制，大型目录下极慢 | 增加 `max_depth` 参数，支持 `*.py` 等 glob 过滤 |
| 无上下文行，LLM 无法定位命中周边的代码 | 支持 `-C`/`--context` 行数控制 |
| 无大小写开关，结果不可预期 | 支持 `-i` 大小写不敏感 |
| 无最大命中数限制，可能返回超长结果 | 增加 `max_matches` 截断与计数 |

### 1.3 目标用户

- **Agent 自身**：调试、代码理解、配置检索等场景需要精确、高效的文件内容搜索
- **开发者**：将 SmallShrimp 作为开发助手时，grep 质量直接影响可用性

---

## 2. 功能范围

### 2.1 MVP（P0 — 必须实现）

| 模块 | 功能 | 说明 |
|------|------|------|
| **grep 工具** | 正则搜索 | 支持 `re.search` 模式，放弃纯字符串 `in` 匹配 |
| **grep 工具** | 参数重设计 | `pattern`(必选)、`path`(搜索目录/文件)、`glob`(文件过滤)、`-i`(大小写)、`max_depth`(递归深度)、`context`(上下行数)、`max_matches`(最大结果数) |
| **grep 工具** | 结果格式化 | 输出格式 `[path:line]: content`，附带命中计数和摘要 |

### 2.2 V1（P1 — 体验完善）

| 模块 | 功能 |
|------|------|
| **grep 工具** | 支持 ripgrep 后端（`rg` 可用时自动启用，纯 Python 兜底） |
| **grep 工具** | 支持反向匹配 `-v`、整词匹配 `-w` |
| **grep 工具** | 大结果分页返回 |

### 2.3 V2（P2 — 高级功能）

| 模块 | 功能 |
|------|------|
| **grep 工具** | 集成索引缓存，首次搜索后缓存文件列表加快二次搜索 |
| **grep 工具** | 并行搜索（多目录并发） |

---

## 3. 技术架构

```
LLM ──► ToolRegistry ──► grep(pattern, path, glob, ...)
                                    │
                         ┌──────────┴──────────┐
                         ▼                     ▼
                   ripgrep (rg)         Python 兜底 (re)
                   可用/更快              无 rg 时回退
                         │                     │
                         └──────────┬──────────┘
                                    ▼
                           格式化结果输出
                           [path:line]: line_content
                           "3 matches in 2 files"
```

### 关键决策

- **主后端选型**：优先检测 `shutil.which('rg')`，有 rg 则 subprocess 调用；无则使用 `pathlib.rglob` + `re.search` 纯 Python 实现
- **Python 兜底性能保障**：通过 `max_depth` + `glob` 过滤 + `max_matches` 上界三路防性能失控
- **与现存 Glob 工具的职责边界**：`glob` 工具只管按模式找文件路径；`grep` 搜文件内容。二者通过 `path` + `glob` 参数组合即可实现"在 *.py 文件里搜 XXX"

---

## 4. 实现设计

### 4.1 函数签名

```python
@tool(name="grep", description="Search file contents with regex. Supports glob filter, context lines, case-insensitive.")
async def grep(
    pattern: str,                              # 正则表达式模式
    path: str = ".",                           # 搜索根目录或文件
    glob: str = "",                            # 文件过滤（如 "*.py" "*.{ts,tsx}"）
    ignore_case: bool = False,                 # -i 大小写不敏感
    max_depth: int = 10,                       # 递归深度限制
    context: int = 0,                          # 上下文行数
    max_matches: int = 200,                    # 最大匹配行数上限
    invert_match: bool = False,                # -v 反向匹配（V1）
    word_regexp: bool = False,                 # -w 整词匹配（V1）
) -> str
```

### 4.2 ripgrep 后端

```python
def _search_with_rg(pattern, path, glob, ignore_case, max_depth, context, max_matches, invert_match, word_regexp) -> str | None:
    """尝试用 ripgrep 搜索。返回 None 表示不可用。"""
    import shutil, subprocess
    if not shutil.which("rg"):
        return None
    cmd = ["rg", "--no-heading", "--line-number", "--color", "never"]
    if ignore_case: cmd.append("-i")
    if max_depth and max_depth > 0: cmd.extend(["--max-depth", str(max_depth)])
    if context > 0: cmd.extend(["-C", str(context)])
    if max_matches: cmd.extend(["-m", str(max_matches)])
    if invert_match: cmd.append("-v")
    if word_regexp: cmd.append("-w")
    if glob: cmd.extend(["-g", glob])
    cmd.append(pattern)
    if path: cmd.append(str(path))
    # ...
```

### 4.3 Python 兜底后端

```python
def _search_python(pattern, path, glob, ignore_case, max_depth, context, max_matches, invert_match, word_regexp) -> str:
    """纯 Python 的正则搜索实现。"""
    import re
    flags = re.IGNORECASE if ignore_case else 0
    compiled = re.compile(pattern, flags)
    # 遍历、匹配、格式化...
```

---

## 5. 后端 API 层设计

无新增 API。仅修改 `tools/builtin_tools.py` 中的 `grep` 函数。

---

## 6. 测试要点

| 场景 | 说明 |
|------|------|
| 正则匹配 | `grep("def \w+")` 匹配所有函数定义 |
| 空结果 | `grep("nonexistent_pattern_xyz")` 返回 "No matches found." |
| 大目录截断 | 确保 `max_matches` 生效，不返回超长结果 |
| rg 不可用 | 无 rg 环境下自动降级到 Python 后端 |
| glob 过滤 | `grep("TODO", glob="*.py")` 只搜 Python 文件 |
| 上下文行 | `grep("error", context=2)` 显示命中前后各 2 行 |

---

## 7. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | 参数重设计 + Python 正则后端实现 + 结果格式化 | 2d |
| P0+ | ripgrep 后端 + 自动降级逻辑 | 1d |
| P1 | `-v` / `-w` / 大结果分页 | 1d |
| P2 | 索引缓存 / 并行搜索 | 2d |

---

## 8. 风险 & 缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| ripgrep 输出格式与 Python 后端不一致 | LLM 困惑 | 两端统一输出格式（`[path:line]: content`），测试覆盖 |
| 超大文件 OOM | Agent 崩溃 | `max_matches` 上界 + 流式读取+截断 |
| Windows 兼容 | ripgrep 不可用 | Python 兜底后端必须完备 |

---

## 9. 附录

### 9.1 参考实现

- **ripgrep**：https://github.com/BurntSushi/ripgrep — Rust 实现的高性能 grep
- **Hermes Agent tools/search_files.py**：已有 rg + Python 双后端模式，可参考其结果格式化与路径处理逻辑

### 9.2 变更文件

| 文件 | 变更类型 |
|------|----------|
| `src/SmallShrimp/tools/builtin_tools.py` | 修改 — grep 函数重写 |
| `tests/test_tools.py` | 新增 — grep 测试用例 |

### 9.3 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始草案 |
