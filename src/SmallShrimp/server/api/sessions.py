"""会话管理 API：列表、创建、删除、重命名。"""

from __future__ import annotations

import json
import uuid
import time
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# 会话元数据文件
META_FILE = "workspace/sessions/.meta.json"


# ─── 数据模型 ──────────────────────────────────────────────

class SessionMeta(BaseModel):
    id: str
    title: str
    agent: str
    created_at: float
    last_active_at: float


class RenameRequest(BaseModel):
    title: str


# ─── 辅助函数 ──────────────────────────────────────────────

def _meta_path() -> Path:
    return Path(META_FILE)


def _load_meta() -> list[dict]:
    p = _meta_path()
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save_meta(meta: list[dict]) -> None:
    p = _meta_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _session_path(session_id: str) -> Path:
    return Path(f"workspace/sessions/{session_id}.jsonl")


# ─── API ──────────────────────────────────────────────────


@router.get("")
async def list_sessions() -> dict:
    """获取会话列表（按最后活跃时间降序）。"""
    meta = _load_meta()
    meta.sort(key=lambda x: x.get("last_active_at", 0), reverse=True)
    return {"sessions": meta}


@router.post("")
async def create_session(agent: str = "pickle") -> dict:
    """创建新会话。"""
    session_id = uuid.uuid4().hex[:12]
    now = time.time()
    meta = _load_meta()
    meta.append({
        "id": session_id,
        "title": "",
        "agent": agent,
        "created_at": now,
        "last_active_at": now,
    })
    _save_meta(meta)
    # 创建空消息文件
    _session_path(session_id).parent.mkdir(parents=True, exist_ok=True)
    _session_path(session_id).touch()
    return {"session_id": session_id}


@router.get("/{session_id}")
async def get_session(session_id: str, offset: int = 0, limit: int = 50) -> dict:
    """获取会话消息历史（分页）。"""
    sp = _session_path(session_id)
    if not sp.exists():
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")

    with open(sp, encoding="utf-8") as f:
        lines = f.readlines()

    total = len(lines)
    messages = [json.loads(l) for l in lines[offset:offset + limit]]
    return {
        "session_id": session_id,
        "messages": messages,
        "has_more": offset + limit < total,
        "total": total,
    }


@router.delete("/{session_id}")
async def delete_session(session_id: str) -> dict:
    """删除会话。"""
    meta = _load_meta()
    new_meta = [m for m in meta if m["id"] != session_id]
    if len(new_meta) == len(meta):
        raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
    _save_meta(new_meta)

    sp = _session_path(session_id)
    if sp.exists():
        sp.unlink()
    return {"deleted": True}


@router.patch("/{session_id}/rename")
async def rename_session(session_id: str, body: RenameRequest) -> dict:
    """重命名会话。"""
    meta = _load_meta()
    for m in meta:
        if m["id"] == session_id:
            m["title"] = body.title
            _save_meta(meta)
            return {"session_id": session_id, "title": body.title}
    raise HTTPException(status_code=404, detail="SESSION_NOT_FOUND")
