"""配置管理 API：读取和写入用户配置。"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigData(BaseModel):
    content: str


@router.get("")
async def get_config() -> dict:
    """读取用户配置。"""
    config_path = _get_workspace() / "config.user.yaml"
    if not config_path.exists():
        return {"content": ""}

    content = config_path.read_text(encoding="utf-8")
    # API Key 脱敏
    lines = content.split("\n")
    masked = [
        _mask_key(line) if "api_key" in line else line
        for line in lines
    ]
    return {"content": "\n".join(masked)}


@router.put("")
async def update_config(body: ConfigData) -> dict:
    """写入用户配置，触发热重载。"""
    config_path = _get_workspace() / "config.user.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(body.content, encoding="utf-8")
    return {"success": True}


# ─── 辅助函数 ──────────────────────────────────────────────


def _get_workspace() -> "Path":
    from pathlib import Path
    return Path("workspace")


def _mask_key(line: str) -> str:
    """将 api_key: sk-abc... 替换为 api_key: sk-****。"""
    if ":" not in line:
        return line
    key, value = line.split(":", 1)
    v = value.strip()
    if len(v) > 8:
        masked = v[:6] + "****"
    else:
        masked = "****"
    return f"{key}: {masked}"
