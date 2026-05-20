from __future__ import annotations
"""Sandbox isolation tests."""
import platform
from src.SmallShrimp.core.sandbox import (
    execute_sandboxed,
    SandboxConfig,
    _clean_env,
    _wrap_os_sandbox,
    _windows_sandbox_available,
    _apply_windows_sandbox,
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


def test_os_sandbox_wraps_command():
    """包装函数返回非空命令列表。"""
    wrapped = _wrap_os_sandbox(["echo", "hello"])
    assert len(wrapped) >= 2
    assert wrapped[-2:] == ["echo", "hello"]


def test_windows_sandbox_no_crash():
    """Windows 沙箱应用不应崩溃。"""
    if platform.system() == "Windows":
        assert _windows_sandbox_available()
        # 应用沙箱不应抛异常
        try:
            _apply_windows_sandbox()
        except Exception as e:
            assert False, f"Windows sandbox crashed: {e}"


if __name__ == "__main__":
    test_execute_safe_command()
    test_execute_command_not_found()
    test_clean_env_strips_dangerous()
    test_sandbox_timeout()
    test_result_truncation()
    test_invalid_syntax()
    test_os_sandbox_wraps_command()
    test_windows_sandbox_no_crash()
    print("All sandbox tests passed!")
