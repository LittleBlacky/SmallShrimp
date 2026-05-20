from __future__ import annotations
"""Sandbox isolation tests."""
from src.SmallShrimp.core.sandbox import (
    execute_sandboxed,
    SandboxConfig,
    _clean_env,
    SandboxResult,
)


def test_execute_safe_command():
    result = execute_sandboxed("python -c \"print('hello world')\"")
    assert result.error == ""
    assert "hello world" in result.stdout


def test_execute_command_not_found():
    result = execute_sandboxed("nonexistent_command_xyz")
    assert result.error != ""


def test_clean_env_strips_dangerous():
    import os
    os.environ["SMALLSHRIMP_TEST_DANGEROUS"] = "should_be_removed"
    clean = _clean_env()
    assert "SMALLSHRIMP_TEST_DANGEROUS" not in clean
    assert "PATH" in clean


def test_sandbox_timeout():
    config = SandboxConfig(timeout=1)
    result = execute_sandboxed("python -c \"import time; time.sleep(5)\"", config)
    assert result.timeout or result.error != ""


def test_result_truncation():
    config = SandboxConfig(max_output=50)
    result = execute_sandboxed("python -c \"print('x' * 5000)\"", config)
    assert result.truncated


def test_invalid_syntax():
    result = execute_sandboxed("")
    assert result.error != ""


if __name__ == "__main__":
    test_execute_safe_command()
    test_execute_command_not_found()
    test_clean_env_strips_dangerous()
    test_sandbox_timeout()
    test_result_truncation()
    test_invalid_syntax()
    print("All sandbox tests passed!")
