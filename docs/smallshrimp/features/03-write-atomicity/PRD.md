# write 工具原子写入 — 产品需求文档

> 版本: v0.1 | 日期: 2026-06-25 | 状态: 草案
> 涉及层: Tools

---

## 1. 产品概述

### 1.1 产品定位

将 `tools/builtin_tools.py` 中的 `write` 工具从直接覆写升级为原子写入模式（写入临时文件 → `os.replace()` 原子重命名），防止写入中断导致目标文件损坏。

### 1.2 核心价值

| 痛点（现状） | 解决 |
|---|---|
| `write(path, content)` 直接调 `Path.write_text()`，写入中断后目标文件可能是半截内容 | 原子重命名保证目标文件要么完整更新、要么完全不变 |
| 并发写入同一文件无保护 | 增加文件锁或临时文件隔离 |
| 无写入确认校验，LLM 不清楚是否成功 | 增加文件大小校验和完整性报告 |
| 大文件写入无进度指示 | 分批写入 + 最终校验（V1） |

### 1.3 目标用户

- **Agent 自身**：当 Agent 使用 write 工具写代码文件、配置文件时，数据完整性至关重要
- **终端用户**：使用 SmallShrimp 作为编码助手时，写操作不可靠会丢失工作成果

---

## 2. 功能范围

### 2.1 MVP（P0 — 必须实现）

| 模块 | 功能 | 说明 |
|------|------|------|
| **write 工具** | 原子写入 | 写入临时文件 → `os.replace()` 原子重命名 |
| **write 工具** | 目录创建 | 自动 `mkdir(parents=True, exist_ok=True)`（已有） |
| **write 工具** | 结果确认 | 返回写入后文件大小、路径 |
| **write 工具** | 临时文件清理 | 在重命名成功后删除临时文件（同目录不同名） |

### 2.2 V1（P1 — 体验完善）

| 模块 | 功能 |
|------|------|
| **write 工具** | 一致性校验（写出 → 读出对比 hash） |
| **write 工具** | `mode` 参数：`overwrite`(覆写) / `append`(追加) / `create`(仅新建) |
| **write 工具** | 大文件分批写入（流式写入临时文件） |

### 2.3 V2（P2 — 高级功能）

| 模块 | 功能 |
|------|------|
| **write 工具** | 写入前备份（`backup=True` 时先生成 `.bak`） |
| **write 工具** | 文件锁定（跨进程） |

---

## 3. 技术架构

### 3.1 当前实现

```python
@tool(name="write", description="Write content to a file.")
async def write(path: str, content: str) -> str:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")  # ← 非原子
    return f"Written {len(content)} characters to {path}"
```

### 3.2 目标实现

```python
@tool(name="write", description="Write content to a file atomically.")
async def write(
    path: str,
    content: str,
    mode: str = "overwrite",       # V1: overwrite / append / create
    backup: bool = False,          # V2: 写入前备份
) -> str:
    file_path = Path(path).resolve()
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # 写入临时文件
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp." + _random_hex())
    try:
        if mode == "append":
            # 读原内容 + 追加（非原子，但可和原子写组合）
            existing = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
            content = existing + content
        elif mode == "create" and file_path.exists():
            return f"Error: {path} already exists (mode=create)"

        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, file_path)  # 原子重命名
    except Exception as e:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise

    written_size = file_path.stat().st_size
    return f"Written {written_size} bytes to {path}"
```

### 3.3 原子写入流程

```
请求 write("/path/to/file.py", "content")
    │
    ├─ 1. 创建临时文件 /path/to/file.py.tmp.ABC123
    ├─ 2. 写入完整内容到临时文件
    ├─ 3. fsync 确保数据落盘
    ├─ 4. os.replace(tmp, target)  ← 原子操作
    │      └─ (POSIX: rename, Windows: MoveFileEx)
    ├─ 5. 返回成功信息
    │
    失败时:
    └─ 清理临时文件，目标文件不变
```

### 3.4 临时文件命名

```python
def _random_hex(length: int = 8) -> str:
    """生成足够随机的临时文件后缀，防冲突。"""
    import secrets
    return secrets.token_hex(length // 2)
```

---

## 4. 后端 API 层设计

无新增 API。仅修改 `tools/builtin_tools.py`。

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `path` | str | 必选 | 目标文件路径 |
| `content` | str | 必选 | 写入内容 |
| `mode` | str | `"overwrite"` | V1: 写入模式 |
| `backup` | bool | `False` | V2: 是否备份原文件 |

---

## 5. 测试要点

| 场景 | 说明 |
|------|------|
| 正常写入 | 写入后文件内容正确、大小匹配 |
| 写入中断（模拟） | 模拟临时文件写入后、replace 前崩溃 — 目标文件不变 |
| 并发写入 | 两个并发 write 同一文件 — 最终结果是完整内容之一 |
| 目录不存在 | 自动创建父目录 |
| 大文件（10MB+） | 写入成功，内容正确 |
| mode=create 已存在 | 返回错误，不覆写 |
| mode=append | 在原内容后追加 |
| backup=True | 原文件被重命名为 `.bak` |

---

## 6. 里程碑

| 阶段 | 内容 | 工期 |
|------|------|------|
| P0 | 原子写入 + 临时文件 + 异常清理 | 1d |
| P0+ | mode 参数（append / create） | 0.5d |
| P1 | 一致性校验（写后校验 hash） | 0.5d |
| P2 | 写入前备份、文件锁定 | 1d |

---

## 7. 风险 & 缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Windows 上 `os.replace` 行为差异 | 跨平台不一致 | Windows 上用 `MoveFileExW` 语义 + fallback 测试 |
| 临时文件残留 | 磁盘占用 | 异常处理中确保清理，提供清理工具 |
| 大文件写入耗时长 | Agent 响应变慢 | 大文件走流式写入 + 分块（V1），设置合理的 max_tokens |

---

## 8. 附录

### 8.1 参考实现

- **Python 标准库 `tempfile`**：`NamedTemporaryFile(delete=False)` + `os.replace`
- **Hermes Agent `tools/file_tools.py`**：`edit_and_apply` 的原子写入模式

### 8.2 变更文件

| 文件 | 变更类型 |
|------|----------|
| `src/SmallShrimp/tools/builtin_tools.py` | 修改 — write 函数重写 |

### 8.3 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-25 | v0.1 | 初始草案 |
