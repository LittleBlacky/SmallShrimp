"""Permission system — control which tools can execute without confirmation.

Mirrors claude-code-from-scratch's permission model:
  - default:       read tools auto-run, write tools ask confirmation
  - acceptEdits:   all tools auto-run
  - bypassPermissions: all tools auto-run (--yolo)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class PermissionMode(str, Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    BYPASS = "bypassPermissions"


# Tools that never need confirmation
SAFE_TOOLS: set[str] = {"read", "glob", "grep", "websearch", "webread", "skill"}

# Tools that always need confirmation in default mode
CONFIRM_TOOLS: set[str] = {"write"}


@dataclass(frozen=True)
class PermissionResult:
    action: str  # "allow" | "deny" | "confirm"
    message: str = ""

    @property
    def is_allowed(self) -> bool:
        return self.action == "allow"

    @property
    def needs_confirmation(self) -> bool:
        return self.action == "confirm"


def check_permission(
    tool_name: str,
    args: dict[str, Any],
    mode: PermissionMode = PermissionMode.DEFAULT,
) -> PermissionResult:
    """Check if a tool call can proceed without confirmation."""

    if mode == PermissionMode.BYPASS:
        return PermissionResult(action="allow")

    # Safe tools always allowed
    if tool_name in SAFE_TOOLS:
        return PermissionResult(action="allow")

    if mode == PermissionMode.ACCEPT_EDITS:
        return PermissionResult(action="allow")

    # Confirm tools need user approval
    if tool_name in CONFIRM_TOOLS:
        path = args.get("path", args.get("file_path", "unknown"))
        return PermissionResult(
            action="confirm",
            message=f"Allow {tool_name} to {path}?",
        )

    # Unknown tools default to confirm
    return PermissionResult(
        action="confirm",
        message=f"Allow {tool_name}?",
    )


# ── Confirmation callback type ──────────────────────────────

ConfirmFn = Callable[[str], "bool | None"]  # None = timeout/abort
