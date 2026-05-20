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
    exact_failure_warn_after: int = 2
    same_tool_failure_warn_after: int = 3
    no_progress_warn_after: int = 2


# ── Decision ─────────────────────────────────────────────────

@dataclass(frozen=True)
class GuardrailDecision:
    action: str = "allow"   # allow | warn
    code: str = ""
    message: str = ""
    tool_name: str = ""
    count: int = 0

    @property
    def allows_execution(self) -> bool:
        return self.action == "allow"

    @property
    def is_warning(self) -> bool:
        return self.action == "warn"


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


# ── Controller ───────────────────────────────────────────────

class ToolGuardrailController:

    def __init__(self, config: GuardrailConfig | None = None) -> None:
        self.config = config or GuardrailConfig()
        self.reset()

    def reset(self) -> None:
        """Reset between turns."""
        self._exact_failures: dict[str, int] = {}       # signature → count
        self._same_tool_failures: dict[str, int] = {}   # tool_name → count
        self._no_progress: dict[str, tuple[str, int]] = {}  # signature → (hash, count)

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
