from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hooks import HookContext, HookManager, HookPermissions, HookPoint, HookResult


DEFAULT_AUDIT_LOG_PATH = "workspace/.cache/hooks/audit.log"
DEFAULT_PRIORITY = 500


def register_builtin_hooks(
    manager: HookManager,
    hooks_config: dict[str, Any] | None,
) -> list[str]:
    """Register enabled code-owned hooks from config."""
    if not isinstance(hooks_config, dict) or not hooks_config.get("enabled", False):
        return []

    builtin_config = hooks_config.get("builtin") or {}
    if not isinstance(builtin_config, dict):
        return []

    registered: list[str] = []
    for name, config in builtin_config.items():
        item = _normalize_config(config)
        if not item.get("enabled", False):
            continue
        if name == "audit_log":
            if _register_audit_log(manager, item):
                registered.append("audit_log")
        elif name == "skill_learning":
            if _register_skill_learning(manager, item):
                registered.append("skill_learning")

    return registered


def _normalize_config(config: Any) -> dict[str, Any]:
    if isinstance(config, bool):
        return {"enabled": config}
    if isinstance(config, dict):
        return config
    return {}


def _priority(config: dict[str, Any]) -> int:
    try:
        value = config.get("priority", DEFAULT_PRIORITY)
        if isinstance(value, bool):
            return DEFAULT_PRIORITY
        return int(value)
    except (TypeError, ValueError):
        return DEFAULT_PRIORITY


def _point(config: dict[str, Any], default: HookPoint) -> HookPoint | None:
    try:
        return HookPoint(config.get("point", default.value))
    except ValueError:
        return None


def _register_audit_log(manager: HookManager, config: dict[str, Any]) -> bool:
    point = _point(config, HookPoint.AFTER_TOOL_CALL)
    if point is None:
        return False

    log_path = Path(str(config.get("path") or DEFAULT_AUDIT_LOG_PATH))

    async def audit_log(ctx: HookContext) -> HookResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "hook_point": ctx.hook_point.value,
            "session_id": ctx.session_id,
            "agent_id": ctx.agent_id,
            "tool_name": ctx.tool_name,
            "failed": ctx.failed,
        }
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return HookResult.observe()

    manager.register(
        point,
        audit_log,
        name="builtin.audit_log",
        priority=_priority(config),
        permissions=HookPermissions(observe=True, write_files=True),
        source="builtin",
    )
    return True


def _register_skill_learning(manager: HookManager, config: dict[str, Any]) -> bool:
    point = _point(config, HookPoint.TASK_COMPLETED)
    if point is None:
        return False

    async def skill_learning(ctx: HookContext) -> HookResult:
        return HookResult(
            action="observe",
            data={"metadata": {"skill_learning_checked": True}},
            message="skill learning checked",
        )

    manager.register(
        point,
        skill_learning,
        name="builtin.skill_learning",
        priority=_priority(config),
        permissions=HookPermissions(observe=True),
        source="builtin",
    )
    return True
