"""内置工具。"""
from pathlib import Path
from ..tools.decorators import tool

@tool(name="read", description="Read the contents of a file. Returns the full text content.")
async def read(path: str) -> str:
    """读取文件内容。"""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not file_path.is_file():
        raise ValueError(f"Not a file: {path}")
    return file_path.read_text(encoding="utf-8")

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

from ..core.skill_loader import SkillLoader
from ..tools.skill_tool import create_skill_tool
from ..tools.web_tools import create_websearch_tool, create_webread_tool
from pathlib import Path

_skill_loader = SkillLoader(Path("workspace/skills"))
skill = create_skill_tool(_skill_loader)
web_search = create_websearch_tool({})
webread = create_webread_tool()