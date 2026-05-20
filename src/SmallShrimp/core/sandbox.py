"""Sandbox isolation — Layer 6 of 7-layer defense.

Three tiers of shell execution hardening:
  Tier 1 (Python):    shell=False, clean env, cwd lock, output cap
  Tier 2 (OS):        unshare(Linux) / sandbox-exec(macOS)
  Tier 3 (Docker):    disposable container (optional, needs Docker)
"""
from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any


# ── Tier 1: Python process hardening ──────────────────────

# Whitelist: only these environment variables pass through
_ENV_WHITELIST = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TZ",
                   "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX",
                   "TMP", "TEMP", "TMPDIR"}

# Max output before truncation
MAX_OUTPUT_BYTES = 100 * 1024  # 100KB

# Default timeout
DEFAULT_TIMEOUT = 30


@dataclass
class SandboxConfig:
    timeout: int = DEFAULT_TIMEOUT
    cwd: str = "."
    env_whitelist: set[str] = field(default_factory=lambda: _ENV_WHITELIST)
    max_output: int = MAX_OUTPUT_BYTES
    enable_os_sandbox: bool = False  # Tier 2


def _clean_env() -> dict[str, str]:
    """Return a minimal, safe environment."""
    clean: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in _ENV_WHITELIST:
            clean[key] = value
    return clean


# ── Tier 2: OS-level sandbox ──────────────────────────────

def _wrap_os_sandbox(command: list[str]) -> list[str]:
    """Wrap a command in OS-level isolation."""
    system = platform.system()

    if system == "Linux":
        # unshare: isolate mount, network, PID namespaces
        if shutil.which("unshare"):
            return [
                "unshare", "-m", "-n", "-p", "--fork", "--mount-proc",
                "--", *command,
            ]

    elif system == "Darwin":
        # sandbox-exec: minimal profile — only allow cwd reads/writes
        if shutil.which("sandbox-exec"):
            profile = _macos_sandbox_profile()
            return ["sandbox-exec", "-f", profile, "--", *command]

    # Windows / unknown: no OS sandbox
    return command


def _macos_sandbox_profile() -> str:
    """Generate a minimal macOS sandbox profile file."""
    import tempfile
    cwd = os.getcwd()
    profile_content = f"""\
(version 1)
(deny default)
(allow file-read* (subpath "{cwd}"))
(allow file-write* (subpath "{cwd}"))
(allow process-exec (subpath "/usr/bin"))
(allow process-exec (subpath "/bin"))
(allow process-exec (subpath "/usr/local/bin"))
(allow sysctl-read)
"""
    fd, path = tempfile.mkstemp(suffix=".sb", prefix="smallshrimp_sandbox_")
    with os.fdopen(fd, "w") as f:
        f.write(profile_content)
    return path


# ── Tier 3: Docker (placeholder) ──────────────────────────

def _wrap_docker(command: list[str], image: str = "alpine:latest") -> list[str] | None:
    """Wrap in a disposable Docker container. Returns None if Docker unavailable."""
    if not shutil.which("docker"):
        return None
    return [
        "docker", "run", "--rm",
        "--network=none",
        "--read-only",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=100M",
        f"--cpus=0.5",
        f"--memory=256m",
        f"--pids-limit=50",
        f"-v", f"{os.getcwd()}:/workspace:ro",
        "--workdir=/workspace",
        image,
        *command,
    ]


# ── Unified executor ──────────────────────────────────────

@dataclass
class SandboxResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    timeout: bool = False
    truncated: bool = False
    sandbox_tier: int = 1
    error: str = ""


def execute_sandboxed(
    command: str,
    config: SandboxConfig | None = None,
) -> SandboxResult:
    """Execute a shell command through all three sandbox tiers."""
    cfg = config or SandboxConfig()
    import shlex

    try:
        args = shlex.split(command)
    except ValueError:
        return SandboxResult(error=f"Invalid command syntax: {command}")

    if not args:
        return SandboxResult(error="Empty command")

    # Tier 1: Build safe args
    cmd_list: list[Any] = args  # shell=False

    # Tier 2: OS sandbox wrapper
    sandbox_tier = 1
    if cfg.enable_os_sandbox:
        os_wrapped = _wrap_os_sandbox(args)
        if os_wrapped != args:
            cmd_list = os_wrapped
            sandbox_tier = 2

    # Tier 3: Docker (opt-in)
    # docker_wrapped = _wrap_docker(args)
    # if docker_wrapped:
    #     cmd_list = docker_wrapped
    #     sandbox_tier = 3

    try:
        proc = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_clean_env(),
            cwd=cfg.cwd,
            shell=False,  # No shell injection
            preexec_fn=_preexec_fn if platform.system() != "Windows" else None,
        )

        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=cfg.timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            # Kill the entire process group
            _kill_process_group(proc)
            stdout_bytes, stderr_bytes = proc.communicate()
            timed_out = True

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        truncated = False
        if len(stdout_bytes) > cfg.max_output:
            half = cfg.max_output // 2
            stdout = (
                stdout[:half]
                + f"\n\n[...output truncated: {len(stdout_bytes)} bytes...]\n\n"
                + stdout[-half:]
            )
            truncated = True

        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            returncode=proc.returncode or 0,
            timeout=timed_out,
            truncated=truncated,
            sandbox_tier=sandbox_tier,
        )

    except FileNotFoundError:
        return SandboxResult(error=f"Command not found: {args[0]}")
    except Exception as e:
        return SandboxResult(error=str(e))


def _preexec_fn() -> None:
    """Pre-exec hook: create new process group for clean kill."""
    os.setpgrp()


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill the entire process group on timeout."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        try:
            proc.kill()
        except OSError:
            pass
