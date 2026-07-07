"""Tool-call loop guardrails — detect stuck patterns in a single turn.

Detects three pathological patterns:
  1. Repeated exact failure — same (tool_name, args) failed N times.
  2. Same tool repeated failure — a single tool failed N times even
     with different arguments (flaky tool).
  3. Read-only no-progress — a read-only tool returned the same hashed
     result M times for the same arguments.

Side-effect free: only returns decisions. The agent loop owns enforcement.
Counters reset between turns.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


# ── Configuration ────────────────────────────────────────────

@dataclass(frozen=True)
class GuardrailConfig:
    warnings_enabled: bool = True
    hard_stop_enabled: bool = False          # explicit opt-in for block/halt
    exact_failure_warn_after: int = 2
    exact_failure_block_after: int = 5
    same_tool_failure_warn_after: int = 3
    same_tool_failure_halt_after: int = 8
    no_progress_warn_after: int = 2
    no_progress_block_after: int = 5

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "GuardrailConfig":
        if not data:
            return cls()
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Decision ─────────────────────────────────────────────────

@dataclass(frozen=True)
class GuardrailDecision:
    action: str = "allow"   # allow | warn | block | halt
    code: str = ""
    message: str = ""
    tool_name: str = ""
    count: int = 0

    @property
    def allows_execution(self) -> bool:
        return self.action in ("allow", "warn")

    @property
    def is_warning(self) -> bool:
        return self.action == "warn"

    @property
    def is_block(self) -> bool:
        return self.action == "block"

    @property
    def is_halt(self) -> bool:
        return self.action == "halt"


# ── Tool Call Signature ──────────────────────────────────────

@dataclass(frozen=True)
class ToolCallSignature:
    tool_name: str
    args_hash: str   # SHA-256 of canonical JSON

    @classmethod
    def create(cls, tool_name: str, args: dict[str, Any] | None) -> "ToolCallSignature":
        return cls(tool_name=tool_name, args_hash=_sha256(_canonical_args(args)))


# ── Helpers ──────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _canonical_args(args: dict[str, Any] | None) -> str:
    """Canonical JSON for args (sorted keys, stable)."""
    if not args:
        return "{}"
    return json.dumps(args, sort_keys=True, ensure_ascii=False)


def _signature(tool_name: str, args: dict[str, Any] | None) -> str:
    """Stable identity: tool_name + sha256(args_canonical)."""
    return f"{tool_name}:{_sha256(_canonical_args(args))}"


# ── Tool Classification ─────────────────────────────────────

IDEMPOTENT_TOOLS: frozenset[str] = frozenset({
    "read", "glob", "grep", "websearch", "webread",
    "skill", "recall_memory", "tool_search",
    "mcp__",  # prefix match handled in is_idempotent()
})

MUTATING_TOOLS: frozenset[str] = frozenset({
    "write", "shell", "remember_profile", "remember_fact",
    "remember_project", "remember_reflection", "remember_constraint",
    "consolidate_memories", "cron_set", "post_message",
    "subagent_dispatch",
})


def is_idempotent(tool_name: str) -> bool:
    if tool_name in IDEMPOTENT_TOOLS:
        return True
    return tool_name.startswith("mcp__")


# ── Controller ───────────────────────────────────────────────

class ToolCallGuardrailController:

    def __init__(self, config: GuardrailConfig | None = None) -> None:
        self.config = config or GuardrailConfig()
        self.reset()

    def reset(self) -> None:
        """Reset between turns."""
        self._exact_failures: dict[str, int] = {}       # signature → count
        self._same_tool_failures: dict[str, int] = {}   # tool_name → count
        self._no_progress: dict[str, tuple[str, int]] = {}  # signature → (hash, count)

    # ── before_call — pre-execution check ───────────────────

    def before_call(
        self,
        tool_name: str,
        args: dict[str, Any] | None,
    ) -> GuardrailDecision:
        """Check if this call should be blocked before execution."""
        if not self.config.hard_stop_enabled:
            return GuardrailDecision(tool_name=tool_name)

        sig = _signature(tool_name, args)

        # Block: same exact failure exceeded threshold
        exact = self._exact_failures.get(sig, 0)
        if exact >= self.config.exact_failure_block_after:
            return GuardrailDecision(
                action="block",
                code="exact_failure_block",
                message=(
                    f"{tool_name} 已用相同参数失败 {exact} 次，已阻断。"
                    f"请改变策略后重试。"
                ),
                tool_name=tool_name,
                count=exact,
            )

        # Halt: same-tool failure exceeded threshold
        same = self._same_tool_failures.get(tool_name, 0)
        if same >= self.config.same_tool_failure_halt_after:
            return GuardrailDecision(
                action="halt",
                code="same_tool_halt",
                message=(
                    f"{tool_name} 本轮已失败 {same} 次，已中止本轮。"
                ),
                tool_name=tool_name,
                count=same,
            )

        return GuardrailDecision(tool_name=tool_name)

    # ── after_call — main hook ─────────────────────────────

    def after_call(
        self,
        tool_name: str,
        args: dict[str, Any] | None,
        result: str | None,
        *,
        failed: bool,
        is_read_only: bool = False,
    ) -> GuardrailDecision:
        sig = _signature(tool_name, args)

        if failed:
            return self._handle_failure(tool_name, args, sig)

        # Success — clear failure counters, check no-progress
        self._exact_failures.pop(sig, None)
        self._same_tool_failures.pop(tool_name, None)

        if not is_read_only:
            self._no_progress.pop(sig, None)
            return GuardrailDecision(tool_name=tool_name)

        return self._handle_no_progress(tool_name, sig, result)

    def _handle_failure(
        self, tool_name: str, args: dict[str, Any] | None, sig: str
    ) -> GuardrailDecision:
        # Exact failure
        exact = self._exact_failures.get(sig, 0) + 1
        self._exact_failures[sig] = exact

        # Same-tool failure
        same = self._same_tool_failures.get(tool_name, 0) + 1
        self._same_tool_failures[tool_name] = same

        self._no_progress.pop(sig, None)

        # Hard stop checks (when enabled)
        if self.config.hard_stop_enabled:
            if exact >= self.config.exact_failure_block_after:
                return GuardrailDecision(
                    action="block",
                    code="exact_failure_block",
                    message=(
                        f"{tool_name} 已用相同参数失败 {exact} 次，已阻断。"
                    ),
                    tool_name=tool_name,
                    count=exact,
                )
            if same >= self.config.same_tool_failure_halt_after:
                return GuardrailDecision(
                    action="halt",
                    code="same_tool_halt",
                    message=(
                        f"{tool_name} 本轮已失败 {same} 次，已中止本轮。"
                    ),
                    tool_name=tool_name,
                    count=same,
                )

        # Warning checks
        if self.config.warnings_enabled and exact >= self.config.exact_failure_warn_after:
            return GuardrailDecision(
                action="warn",
                code="exact_failure",
                message=(
                    f"{tool_name} 已用相同参数失败 {exact} 次。"
                    f"请检查错误原因并改变策略，不要重复相同调用。"
                ),
                tool_name=tool_name,
                count=exact,
            )

        if self.config.warnings_enabled and same >= self.config.same_tool_failure_warn_after:
            return GuardrailDecision(
                action="warn",
                code="same_tool_failure",
                message=(
                    f"{tool_name} 本轮已失败 {same} 次。"
                    f"该工具可能不可用，请换一种方式。"
                ),
                tool_name=tool_name,
                count=same,
            )

        return GuardrailDecision(tool_name=tool_name, count=exact)

    def _handle_no_progress(
        self, tool_name: str, sig: str, result: str | None
    ) -> GuardrailDecision:
        result_hash = _sha256(result or "")
        prev = self._no_progress.get(sig)
        repeat = 1
        if prev is not None and prev[0] == result_hash:
            repeat = prev[1] + 1
        self._no_progress[sig] = (result_hash, repeat)

        if self.config.hard_stop_enabled and repeat >= self.config.no_progress_block_after:
            return GuardrailDecision(
                action="block",
                code="no_progress_block",
                message=(
                    f"{tool_name} 已返回相同结果 {repeat} 次，已阻断。"
                ),
                tool_name=tool_name,
                count=repeat,
            )

        if self.config.warnings_enabled and repeat >= self.config.no_progress_warn_after:
            return GuardrailDecision(
                action="warn",
                code="no_progress",
                message=(
                    f"{tool_name} 已返回相同结果 {repeat} 次。"
                    f"请复用已有结果或改变查询方式，不要重复相同调用。"
                ),
                tool_name=tool_name,
                count=repeat,
            )

        return GuardrailDecision(tool_name=tool_name, count=repeat)


# ── Render ──────────────────────────────────────────────────

def append_guardrail_warning(result: str, decision: GuardrailDecision) -> str:
    """将 guardrail 警告附加到工具结果末尾。"""
    if not decision.is_warning or not decision.message:
        return result
    return f"{result}\n\n[Tool Loop Warning: {decision.code}; {decision.message}]"


def guardrail_synthetic_result(decision: GuardrailDecision) -> str:
    """为被 block/halt 的工具调用生成合成结果。"""
    return f"[Tool blocked: {decision.code}; {decision.message}]"


ToolGuardrailController = ToolCallGuardrailController
