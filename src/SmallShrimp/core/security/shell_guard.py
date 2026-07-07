"""Shell command guard — Layer 4: tree-sitter Bash AST analysis.

Parses shell commands into a Concrete Syntax Tree using tree-sitter,
then walks the AST to detect dangerous patterns with quote awareness.

Key advantage: understands shell grammar — "echo 'rm -rf /'" is safe
(rm is inside a quoted string), while regex-based approaches would
false-positive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import tree_sitter_bash as tsb
from tree_sitter import Language, Parser

_parser: Parser | None = None


def _get_parser() -> Parser:
    global _parser
    if _parser is None:
        lang = Language(tsb.language())
        _parser = Parser(lang)
    return _parser


def parse_command(command: str) -> Any:
    try:
        tree = _get_parser().parse(command.encode())
        return tree.root_node
    except Exception:
        return None


# ── Node types ─────────────────────────────────────────────

_DANGEROUS_REDIRECT_TARGETS = {
    "/dev/sda", "/dev/sdb", "/dev/sdc", "/dev/sdd",
}

_BLOCKED_PROGRAMS = {
    "sudo", "su", "reboot", "shutdown", "mkfs", "dd",
    "format", "taskkill",
}

_WARN_PROGRAMS = {
    "rm", "kill", "pkill", "killall", "chmod", "chown",
    "nc", "ncat", "del", "rmdir",
    "curl", "wget",
}

_DESTRUCTIVE_FLAGS = {
    "-rf", "-r", "-f", "--force", "--hard", "-9", "-Recurse",
}


@dataclass
class ShellCheckResult:
    safe: bool = True
    warnings: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return len(self.blocked) > 0


# ── AST walker ────────────────────────────────────────────

def check_shell_command(command: str) -> ShellCheckResult:
    result = ShellCheckResult()
    root = parse_command(command)
    if root is None:
        result.blocked.append("failed to parse command")
        result.safe = False
        return result
    _walk_node(root, command, result)
    if result.blocked:
        result.safe = False
    return result


def _walk_node(node: Any, source: str, result: ShellCheckResult, depth: int = 0) -> None:
    node_type = node.type

    # Redirect targets
    if node_type == "file_redirect":
        target_text = source[node.start_byte:node.end_byte]
        for target in _DANGEROUS_REDIRECT_TARGETS:
            if target in target_text:
                result.blocked.append(f"redirect to {target}")

    # Pipeline: curl/wget → shell
    if node_type == "pipeline":
        cmd_text = source[node.start_byte:node.end_byte]
        has_dl = any(c in cmd_text for c in ("curl", "wget"))
        has_sh = any(c in cmd_text for c in ("bash", "sh", "zsh"))
        if has_dl and has_sh:
            if not _is_quoted_pipeline(node, source):
                result.blocked.append("dangerous pipe: curl/wget → shell")

    # Command
    if node_type == "command":
        _check_command_node(node, source, result)

    # Subshell
    if node_type == "command_substitution":
        sub_text = source[node.start_byte:node.end_byte]
        result.warnings.append(f"command substitution: {sub_text[:60]}")

    for child in node.children:
        _walk_node(child, source, result, depth + 1)


def _check_command_node(node: Any, source: str, result: ShellCheckResult) -> None:
    cmd_name = ""
    flags: list[str] = []

    for child in node.children:
        if child.type == "command_name":
            cmd_name = source[child.start_byte:child.end_byte].strip()
        elif child.type in ("word", "number", "string") and not cmd_name:
            cmd_name = source[child.start_byte:child.end_byte].strip()
        elif child.type in ("word", "number", "string") and cmd_name:
            text = source[child.start_byte:child.end_byte].strip()
            if text.startswith("-"):
                flags.append(text)

    if not cmd_name:
        return

    cmd_lower = cmd_name.lower()

    if cmd_lower in _BLOCKED_PROGRAMS or any(p in cmd_lower for p in _BLOCKED_PROGRAMS):
        result.blocked.append(f"blocked: {cmd_name}")
        return

    if cmd_lower in _WARN_PROGRAMS:
        has_destructive = any(f in _DESTRUCTIVE_FLAGS for f in flags)
        if has_destructive:
            result.blocked.append(f"{cmd_name} with destructive: {', '.join(flags)}")
        else:
            result.warnings.append(f"{cmd_name}: use with caution")


def _is_quoted_pipeline(node: Any, source: str) -> bool:
    """Check if pipeline content is entirely quoted."""
    text = source[node.start_byte:node.end_byte].strip()
    return (text.startswith('"') and text.endswith('"')) or \
           (text.startswith("'") and text.endswith("'"))
