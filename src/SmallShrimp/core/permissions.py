"""Permission system — 7-layer defense-in-depth.

Layers implemented:
  2. Permission modes (default/acceptEdits/bypass/plan/dontAsk)
  3. Permission rules file (workspace/permissions.json)
  5. Tool-level path validation (boundary + system protection)
  7. User confirmation (CLI + confirm_fn)

+ Path whitelist: confirmed paths don't re-ask within a session.
"""
from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class PermissionMode(str, Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    BYPASS = "bypassPermissions"
    PLAN = "plan"
    DONT_ASK = "dontAsk"


SAFE_TOOLS: set[str] = {"read", "glob", "grep", "websearch", "webread", "skill"}
CONFIRM_TOOLS: set[str] = {"write"}
PLAN_TOOLS: set[str] = {}

# Protected paths — never allow writes (Layer 5)
_PROTECTED_GLOBS = [
    ".env", ".env.*", ".git", ".git/**", ".gitignore",
    "C:\\Windows\\**", "C:\\WINDOWS\\**",
    "/etc/**", "/bin/**", "/usr/**", "/boot/**", "/sys/**", "/dev/**",
    "**/System32/**", "**/system32/**",
]

# Default workspace boundary — writes only allowed inside
_WORKSPACE_BOUNDARY: str | None = None


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

    @property
    def is_denied(self) -> bool:
        return self.action == "deny"


ConfirmFn = Callable[[str], "bool | None"]


# ── Layer 3: Permission rules file ────────────────────────

@dataclass
class PermissionRule:
    tool: str = "*"
    path: str = "*"
    action: str = "allow"  # allow | deny | ask

    @classmethod
    def from_dict(cls, d: dict) -> "PermissionRule":
        return cls(
            tool=d.get("tool", "*"),
            path=d.get("path", "*"),
            action=d.get("action", "allow"),
        )

    def matches(self, tool_name: str, file_path: str) -> bool:
        tool_match = self.tool == "*" or fnmatch.fnmatch(tool_name, self.tool)
        path_match = self.path == "*" or fnmatch.fnmatch(file_path, self.path)
        return tool_match and path_match


@dataclass
class PermissionRules:
    deny: list[PermissionRule] = field(default_factory=list)
    allow: list[PermissionRule] = field(default_factory=list)
    ask: list[PermissionRule] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str) -> "PermissionRules":
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return cls(
                deny=[PermissionRule.from_dict(r) for r in data.get("deny", [])],
                allow=[PermissionRule.from_dict(r) for r in data.get("allow", [])],
                ask=[PermissionRule.from_dict(r) for r in data.get("ask", [])],
            )
        except Exception:
            return cls()


# ── Layer 5: Path validation ─────────────────────────────

def validate_path(path: str, workspace_root: str | None = None) -> str | None:
    """Validate a file path for writes. Returns error message or None."""
    if not path:
        return "Empty path"

    basename = os.path.basename(path)
    for pattern in _PROTECTED_GLOBS:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(basename, pattern):
            return f"Protected path: {path} matches {pattern}"

    # Workspace boundary check
    ws = workspace_root or _WORKSPACE_BOUNDARY
    if ws:
        ws_abs = str(Path(ws).resolve())
        try:
            target = Path(path).resolve() if os.path.isabs(path) else Path(os.getcwd()) / path
            target_abs = str(target.resolve())
            if not target_abs.startswith(ws_abs):
                return f"Path outside workspace: {path}"
        except Exception:
            return f"Invalid path: {path}"

    return None


def set_workspace_boundary(path: str) -> None:
    global _WORKSPACE_BOUNDARY
    _WORKSPACE_BOUNDARY = path


# ── Layer 2+3+5: Unified checker ─────────────────────────

class PermissionChecker:
    """Stateful permission checker: mode + rules + path validation + whitelist."""

    def __init__(
        self,
        mode: PermissionMode = PermissionMode.DEFAULT,
        rules: PermissionRules | None = None,
        workspace_root: str | None = None,
    ):
        self.mode = mode
        self.rules = rules or PermissionRules()
        self.workspace_root = workspace_root
        self._confirmed_paths: set[str] = set()

    def reset(self) -> None:
        self._confirmed_paths.clear()

    def check(self, tool_name: str, args: dict[str, Any]) -> PermissionResult:
        path = args.get("path", args.get("file_path", ""))

        # ── Layer 5: Path validation for write tools ──
        if tool_name in CONFIRM_TOOLS and path:
            err = validate_path(path, self.workspace_root)
            if err:
                return PermissionResult(action="deny", message=err)

        # ── Layer 4: Shell command guard ──
        if tool_name == "shell":
            from ..core.shell_guard import check_shell_command
            cmd = args.get("command", "")
            if cmd:
                check = check_shell_command(cmd)
                if check.is_blocked:
                    return PermissionResult(
                        action="deny",
                        message=f"Blocked: {', '.join(check.blocked)}",
                    )

        # ── Layer 3: Deny rules (override everything including bypass) ──
        for rule in self.rules.deny:
            if rule.matches(tool_name, path):
                return PermissionResult(action="deny", message=f"Denied by rule: {tool_name}({path})")

        # ── Layer 2: Bypass mode ──
        if self.mode == PermissionMode.BYPASS:
            return PermissionResult(action="allow")

        # Safe tools + plan tools always allowed
        if tool_name in SAFE_TOOLS or tool_name in PLAN_TOOLS:
            return PermissionResult(action="allow")

        # ── Layer 3: Permission rules ──
        # Deny rules first (highest priority)
        for rule in self.rules.deny:
            if rule.matches(tool_name, path):
                return PermissionResult(
                    action="deny",
                    message=f"Denied by rule: {tool_name}({path})",
                )
        # Allow rules
        for rule in self.rules.allow:
            if rule.matches(tool_name, path):
                return PermissionResult(action="allow")
        # Ask rules
        for rule in self.rules.ask:
            if rule.matches(tool_name, path):
                return PermissionResult(
                    action="confirm",
                    message=f"Ask by rule: {tool_name} to {path}?" if path else f"Ask by rule: {tool_name}?",
                )

        # ── Layer 2: Mode logic ──
        if self.mode == PermissionMode.ACCEPT_EDITS and tool_name in CONFIRM_TOOLS:
            return PermissionResult(action="allow")

        # Path whitelist
        if path and path in self._confirmed_paths:
            return PermissionResult(action="allow")

        if self.mode == PermissionMode.PLAN and tool_name in CONFIRM_TOOLS:
            return PermissionResult(action="deny", message=f"Blocked in plan: {tool_name}({path})")

        if self.mode == PermissionMode.DONT_ASK:
            return PermissionResult(action="deny", message=f"Auto-denied: {tool_name}({path})")

        if tool_name in CONFIRM_TOOLS:
            return PermissionResult(
                action="confirm",
                message=f"Allow {tool_name} to {path}?" if path else f"Allow {tool_name}?",
            )

        return PermissionResult(action="confirm", message=f"Allow {tool_name}?")

    def confirm_path(self, path: str) -> None:
        if path:
            self._confirmed_paths.add(path)


# ── Legacy ──────────────────────────────────────────────

def check_permission(
    tool_name: str, args: dict[str, Any],
    mode: PermissionMode = PermissionMode.DEFAULT,
) -> PermissionResult:
    return PermissionChecker(mode).check(tool_name, args)



ConfirmFn = Callable[[str], "bool | None"]  # None = timeout/abort
