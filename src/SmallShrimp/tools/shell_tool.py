"""Shell execution tool — Layer 4 AST + Layer 6 sandbox."""
from __future__ import annotations

from ..tools.decorators import tool


@tool(
    name="shell",
    description=(
        "Execute a shell command. "
        "Dangerous commands (rm -rf, sudo, curl|bash, etc.) are blocked. "
        "Runs in sandbox: no shell injection, clean env, timeout, output cap."
    ),
)
async def shell(command: str, timeout: int = 30) -> str:
    """Execute a shell command with AST check + sandbox isolation."""
    from ..core.shell_guard import check_shell_command
    from ..core.sandbox import execute_sandboxed, SandboxConfig

    # Layer 4: Bash AST check
    check = check_shell_command(command)
    if check.is_blocked:
        return (
            f"Error: Command blocked by shell guard.\n"
            f"Blocked: {', '.join(check.blocked)}\n"
            + (f"Warnings: {', '.join(check.warnings)}" if check.warnings else "")
        )

    # Layer 6: Sandbox execution
    cfg = SandboxConfig(timeout=min(timeout, 120))
    result = execute_sandboxed(command, cfg)

    if result.error:
        return f"Error: {result.error}"

    if result.timeout:
        return f"Error: Command timed out after {cfg.timeout}s"

    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"

    if result.returncode != 0:
        output += f"\n[exit code: {result.returncode}]"

    if result.truncated:
        output += "\n\n[output was truncated]"

    if check.warnings:
        output += f"\n\n[Shell warnings: {', '.join(check.warnings)}]"

    output += f"\n[sandbox tier: {result.sandbox_tier}]"

    return output or "(no output)"
