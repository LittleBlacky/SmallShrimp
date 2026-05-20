"""Shell command guard — Layer 4 defense: Bash AST / pattern analysis.

Parses shell commands to detect dangerous patterns. Uses enhanced regex
matching (tree-sitter would be ideal but adds a heavy dependency).

23 safety checks covering:
  - Destructive file ops (rm, dd, mkfs)
  - Privilege escalation (sudo, su)
  - System control (reboot, shutdown, kill)
  - Data exfiltration (curl/wget pipe, /dev/tcp)
  - Git destructive (push --force, hard reset, clean -f)
  - Windows destructive (del, rmdir, format, Remove-Item)
  - Dangerous pipes and redirects
  - Command chaining with destructive ops
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from typing import Callable


# ── Dangerous patterns (aligned with claude-code-from-scratch) ──

_DANGEROUS_PATTERNS: list[tuple[str, str]] = [
    # Destructive filesystem
    (r"\brm\s+-rf\b", "rm -rf (recursive delete)"),
    (r"\brm\s+-r\b", "rm -r (recursive delete)"),
    (r"\brm\b", "rm (delete files) — use with caution"),
    (r"\bdd\s+if=", "dd (disk copy)"),
    (r"\bmkfs\.", "mkfs (format filesystem)"),
    (r">\s*/dev/sd", "write to block device"),
    # Privilege escalation
    (r"\bsudo\b", "sudo (privilege escalation)"),
    (r"\bsu\s+-", "su (switch user)"),
    (r"\bchmod\s+777\b", "chmod 777 (world-writable)"),
    (r"\bchmod\s\+s\b", "chmod +s (setuid)"),
    # System control
    (r"\breboot\b", "reboot"),
    (r"\bshutdown\b", "shutdown"),
    (r"\bkill\s+-9\b", "kill -9 (force kill)"),
    (r"\bpkill\b", "pkill"),
    (r"\bkillall\b", "killall"),
    # Data exfiltration
    (r"\bcurl\b.*\|.*\bbash\b", "curl pipe to bash"),
    (r"\bwget\b.*\|.*\bbash\b", "wget pipe to bash"),
    (r">\s*/dev/tcp/", "write to /dev/tcp"),
    (r"\bnc\s+-e\b", "netcat -e (backdoor)"),
    # Git destructive
    (r"\bgit\s+push\s+.*--force", "git push --force"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard"),
    (r"\bgit\s+clean\s+-f[d-x]*\b", "git clean -f"),
    # Windows destructive
    (r"\bdel\s+/[fq]", "del /f (Windows force delete)"),
    (r"\brmdir\s+/s\b", "rmdir /s (Windows recursive)"),
    (r"\bformat\s+[a-z]:", "format drive (Windows)"),
    (r"\bRemove-Item\s+-Recurse", "Remove-Item -Recurse (PowerShell)"),
    # Command chaining abuse
    (r"\brm\b.*&&.*\brm\b", "chained rm commands"),
    (r"\beval\s", "eval (code injection risk)"),
]

_COMPILED_DANGEROUS = [(re.compile(p, re.IGNORECASE), desc) for p, desc in _DANGEROUS_PATTERNS]

# ── Parsed command ──────────────────────────────────────────

@dataclass
class ParsedCommand:
    raw: str
    program: str = ""
    args: list[str] = field(default_factory=list)
    has_pipe: bool = False
    has_redirect: bool = False
    has_backtick: bool = False
    has_dollar_sub: bool = False

    @classmethod
    def parse(cls, command: str) -> "ParsedCommand":
        pc = cls(raw=command)
        pc.has_pipe = "|" in command
        pc.has_redirect = ">" in command or ">>" in command
        pc.has_backtick = "`" in command
        pc.has_dollar_sub = "$(" in command

        # Parse first word as program
        try:
            tokens = shlex.split(command)
            if tokens:
                pc.program = tokens[0]
                pc.args = tokens[1:]
        except ValueError:
            pc.program = command.split()[0] if command.split() else ""

        return pc


# ── Checker ─────────────────────────────────────────────────

@dataclass
class ShellCheckResult:
    safe: bool = True
    warnings: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return len(self.blocked) > 0


def check_shell_command(command: str) -> ShellCheckResult:
    """Analyze a shell command for dangerous patterns. Returns structured result."""
    result = ShellCheckResult()
    parsed = ParsedCommand.parse(command)

    # Check command level (most reliable)
    if parsed.program:
        prog_result = _check_program(parsed.program)
        if not prog_result.safe:
            result.blocked.extend(prog_result.warnings)

    # Check full command for dangerous patterns
    for pattern, desc in _COMPILED_DANGEROUS:
        if pattern.search(command):
            if _is_critical(desc):
                result.blocked.append(desc)
            else:
                result.warnings.append(desc)

    # Structural checks
    if parsed.has_backtick:
        result.warnings.append("backtick command substitution")
    if parsed.has_dollar_sub:
        result.warnings.append("$(...) command substitution")
    if parsed.has_pipe and any(destructive in command for destructive in ["rm", "kill", "sudo"]):
        result.warnings.append("pipe with destructive command")

    # Determine safety
    if result.blocked:
        result.safe = False

    return result


def _check_program(program: str) -> ShellCheckResult:
    """Check if the program itself is dangerous."""
    DANGEROUS_PROGRAMS = {
        "dd", "mkfs", "sudo", "su", "reboot", "shutdown",
        "pkill", "killall", "chmod", "chown",
        "nc", "ncat", "eval", "exec",
        "format", "del", "rmdir", "taskkill",
    }
    program_lower = program.lower()
    if program_lower in DANGEROUS_PROGRAMS:
        return ShellCheckResult(safe=False, warnings=[f"dangerous program: {program}"])
    return ShellCheckResult(safe=True)


def _is_critical(desc: str) -> bool:
    """Determine if a pattern is critical (block) vs warning."""
    CRITICAL = {
        "rm -rf", "dd (disk copy)", "mkfs (format filesystem)",
        "sudo (privilege escalation)", "reboot", "shutdown",
        "curl pipe to bash", "wget pipe to bash",
        "write to block device", "format drive (Windows)",
    }
    return any(c in desc for c in CRITICAL)
