from __future__ import annotations
"""Permission system 测试。"""
from src.SmallShrimp.core.permissions import (
    check_permission,
    PermissionMode,
    PermissionResult,
    SAFE_TOOLS,
    CONFIRM_TOOLS,
)


def test_read_tools_always_allowed():
    for name in SAFE_TOOLS:
        r = check_permission(name, {}, PermissionMode.DEFAULT)
        assert r.is_allowed, f"{name} should be allowed"


def test_write_needs_confirm_in_default():
    r = check_permission("write", {"path": "test.txt"}, PermissionMode.DEFAULT)
    assert r.needs_confirmation
    assert "test.txt" in r.message


def test_bypass_allows_write():
    r = check_permission("write", {"path": "test.txt"}, PermissionMode.BYPASS)
    assert r.is_allowed


def test_accept_edits_allows_write():
    r = check_permission("write", {"path": "test.txt"}, PermissionMode.ACCEPT_EDITS)
    assert r.is_allowed


def test_unknown_tool_needs_confirm():
    r = check_permission("delete", {"path": "test.txt"}, PermissionMode.DEFAULT)
    assert r.needs_confirmation


def test_permission_result_properties():
    r = PermissionResult(action="allow")
    assert r.is_allowed
    assert not r.needs_confirmation

    r2 = PermissionResult(action="confirm", message="ask")
    assert not r2.is_allowed
    assert r2.needs_confirmation


if __name__ == "__main__":
    test_read_tools_always_allowed()
    test_write_needs_confirm_in_default()
    test_bypass_allows_write()
    test_accept_edits_allows_write()
    test_unknown_tool_needs_confirm()
    test_permission_result_properties()
    print("All permission tests passed!")
