"""内置工具。"""
from pathlib import Path
from ..tools.decorators import tool

@tool(name="read", description="Read a file. offset/limit are line numbers. With no params returns whole file (auto-paginated if large).")
async def read(path: str, offset: int = 0, limit: int | None = None) -> str:
    """读取文件内容。offset 起始行，limit 最大行数。大文件自动分页。"""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not file_path.is_file():
        raise ValueError(f"Not a file: {path}")
    lines = file_path.read_text(encoding="utf-8").split("\n")
    total = len(lines)
    if offset:
        lines = lines[offset:]
    if limit:
        lines = lines[:limit]

    PAGE_CHARS = 8000  # 每页约 8000 字符
    result = "\n".join(lines)
    if len(result) <= PAGE_CHARS or limit:
        # 小文件或指定了 limit → 直接返回
        if offset or limit:
            return f"[Lines {offset}-{offset + len(lines)} of {total}]\n{result}"
        return result

    # 大文件自动分页
    pages = []
    line_offset = offset
    for i in range(0, len(lines), 200):  # 每页约 200 行
        chunk = lines[i:i + 200]
        chunk_text = "\n".join(chunk)
        start = line_offset + i
        end = line_offset + i + len(chunk) - 1
        pages.append(f"[Page {len(pages) + 1} — Lines {start}-{end} of {total}]\n{chunk_text}")
        if len(pages) >= 20:  # 最多 20 页
            pages.append(f"[... {total - end - 1} more lines, use read(path, offset={end + 1}) to continue]")
            break

    return "\n\n".join(pages)

@tool(name="write", description="Write content to a file. Creates or overwrites the file.")
async def write(path: str, content: str) -> str:
    """写入文件内容。"""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"Written {len(content)} characters to {path}"

@tool(name="glob", description="Search for files matching a glob pattern.")
async def glob(pattern: str) -> str:
    """搜索文件。"""
    from pathlib import Path as P
    files = list(Path(".").glob(pattern))
    if not files:
        return "No files found."
    return "\n".join([str(f) for f in files])

@tool(name="grep", description="Search for text within files.")
async def grep(pattern: str, path: str = ".") -> str:
    """搜索文件内容。"""
    results = []
    from pathlib import Path
    for f in Path(path).rglob("*"):
        if f.is_file():
            try:
                content = f.read_text(encoding="utf-8")
                if pattern in content:
                    results.append(f"{f}: found '{pattern}'")
            except Exception:
                pass
    return "\n".join(results) if results else "No matches found."