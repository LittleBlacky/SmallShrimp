"""内置工具。"""
from pathlib import Path
from ..tools.decorators import tool

READ_DEFAULT_LIMIT = 500   # read 默认行数上限，防单次结果过大
GREP_DEFAULT_LIMIT = 200   # grep 默认匹配数上限
GLOB_DEFAULT_LIMIT = 500   # glob 默认文件数上限


@tool(name="read", description="Read a file. offset/limit in lines. Default limit=500, set limit=0 for full file.")
async def read(path: str, offset: int = 0, limit: int = READ_DEFAULT_LIMIT) -> str:
    """读取文件内容。默认返回前 500 行，传 limit=0 获取完整文件。"""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not file_path.is_file():
        raise ValueError(f"Not a file: {path}")
    lines = file_path.read_text(encoding="utf-8").split("\n")
    total = len(lines)
    if offset:
        lines = lines[offset:]
    if limit and limit > 0:
        lines = lines[:limit]
    result = "\n".join(lines)
    end_line = offset + len(lines) - 1
    return f"[Lines {offset}-{end_line} of {total}]\n{result}"

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