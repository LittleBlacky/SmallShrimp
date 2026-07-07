from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

from .hooks import HookContext, HookManager, HookPermissions, HookPoint, HookResult

logger = logging.getLogger(__name__)


@dataclass
class UserHookConfig:
    name: str
    enabled: bool
    module: str
    handler: str
    point: str
    timeout_ms: int = 1000
    priority: int = 500
    permissions: dict[str, Any] = field(default_factory=dict)


def configs_from_mapping(hooks_config: dict[str, Any] | None) -> list[UserHookConfig]:
    """Parse trusted runtime config into controlled user hook configs."""
    if not isinstance(hooks_config, dict) or not hooks_config.get("enabled", False):
        return []

    user_config = hooks_config.get("user") or {}
    if not isinstance(user_config, dict):
        return []

    configs: list[UserHookConfig] = []
    for name, raw_config in user_config.items():
        item = _normalize_config(raw_config)
        if not item.get("enabled", False):
            continue

        module = item.get("module")
        handler = item.get("handler")
        point = item.get("point")
        if not all(isinstance(value, str) and value for value in (module, handler, point)):
            logger.warning("Skipping malformed user hook config: %s", name)
            continue

        permissions = item.get("permissions")
        configs.append(
            UserHookConfig(
                name=str(name),
                enabled=True,
                module=module,
                handler=handler,
                point=point,
                timeout_ms=_int_config(item.get("timeout_ms"), 1000),
                priority=_int_config(item.get("priority"), 500),
                permissions=permissions if isinstance(permissions, dict) else {},
            )
        )
    return configs


def load_user_hooks(
    manager: HookManager,
    configs: list[UserHookConfig],
    workspace: str | Path,
) -> list[str]:
    workspace_path = Path(workspace).resolve()
    allowed_root = (workspace_path / "hooks").resolve()
    loaded: list[str] = []

    for config in configs:
        if not config.enabled:
            continue

        hook_point = _parse_hook_point(config)
        if hook_point is None:
            continue

        module_path = _resolve_module_path(config.module, workspace_path)
        if not _is_relative_to(module_path, allowed_root):
            logger.warning("Skipping user hook outside workspace hooks directory: %s", module_path)
            continue
        if not module_path.exists():
            logger.warning("Skipping missing user hook: %s", module_path)
            continue
        if module_path.suffix != ".py":
            logger.warning("Skipping non-Python user hook: %s", module_path)
            continue

        handler = _load_handler(module_path, config.handler)
        if handler is None:
            continue

        manager.register(
            hook_point,
            _with_timeout(handler, config.timeout_ms),
            name=f"user.{config.name}",
            priority=config.priority,
            permissions=_parse_permissions(config.permissions),
            source="user",
        )
        loaded.append(config.name)

    return loaded


def _normalize_config(config: Any) -> dict[str, Any]:
    if isinstance(config, bool):
        return {"enabled": config}
    if isinstance(config, dict):
        return config
    return {}


def _int_config(value: Any, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_hook_point(config: UserHookConfig) -> HookPoint | None:
    try:
        return HookPoint(config.point)
    except ValueError:
        logger.warning("Skipping user hook %s with invalid hook point: %s", config.name, config.point)
        return None


def _resolve_module_path(module: str, workspace: Path) -> Path:
    module_path = Path(module)
    if not module_path.is_absolute():
        module_path = workspace / module_path
    return module_path.resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _load_handler(module_path: Path, handler_name: str) -> Callable[[HookContext], Any] | None:
    module_name = f"smallshrimp_user_hook_{abs(hash(module_path))}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            logger.warning("Skipping user hook with unloadable module spec: %s", module_path)
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        logger.exception("Failed to load user hook module: %s", module_path)
        return None

    handler = getattr(module, handler_name, None)
    if not callable(handler):
        logger.warning("Skipping user hook with missing callable handler %s: %s", handler_name, module_path)
        return None
    return handler


def _parse_permissions(raw_permissions: dict[str, Any]) -> HookPermissions:
    valid_fields = {item.name for item in fields(HookPermissions)}
    return HookPermissions(
        **{
            key: value
            for key, value in raw_permissions.items()
            if key in valid_fields
        }
    )


def _with_timeout(
    handler: Callable[[HookContext], Any],
    timeout_ms: int,
) -> Callable[[HookContext], Any]:
    async def wrapped(ctx: HookContext) -> HookResult:
        timeout_seconds = max(timeout_ms, 1) / 1000
        try:
            result = await asyncio.wait_for(_call_handler(handler, ctx), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning("User hook timed out: %s", getattr(handler, "__name__", "hook"))
            return HookResult.observe("user hook timed out")

        if isinstance(result, HookResult):
            return result
        return HookResult.observe()

    return wrapped


async def _call_handler(handler: Callable[[HookContext], Any], ctx: HookContext) -> Any:
    if inspect.iscoroutinefunction(handler):
        return await handler(ctx)

    result = await asyncio.to_thread(handler, ctx)
    if inspect.isawaitable(result):
        return await result
    return result
