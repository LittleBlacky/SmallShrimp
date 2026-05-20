"""Shell execution tool — with Layer 4 Bash AST guard."""
from __future__ import annotations

import subprocess
from ..tools.decorators import tool


@tool(
    name="shell",
    description=(
        "Execute a shell command. "
        "Dangerous commands (rm -rf, sudo, curl|bash, etc.) are blocked. "
        "Use for running scripts, building, testing, and system queries."
    ),
)
async def shell(command: str, timeout: int = 30) -> str:
    """Execute a shell command with safety checks. Returns stdout/stderr."""
    from ..core.shell_guard import check_shell_command

    # Layer 4: Bash AST check
    check = check_shell_command(command)
    if check.is_blocked:
        return (
            f"Error: Command blocked by shell guard.\n"
            f"Blocked patterns: {', '.join(check.blocked)}\n"
            + (f"Warnings: {', '.join(check.warnings)}" if check.warnings else "")
        )

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=min(timeout, 120),
            cwd=".",
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"

        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"

        # Warning suffix
        if check.warnings:
            output += f"\n\n[Shell warnings: {', '.join(check.warnings)}]"

        # Truncate large output
        if len(output) > 10000:
            output = output[:5000] + f"\n\n[...output truncated: {len(output)} chars total...]\n\n" + output[-5000:]

        return output or "(no output)"

    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"
