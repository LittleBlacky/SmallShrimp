from __future__ import annotations
"""Permission system 测试。"""
import tempfile, os, json
from src.SmallShrimp.core.permissions import (
    PermissionChecker, PermissionMode, PermissionResult,
    PermissionRules, PermissionRule,
    validate_path, set_workspace_boundary,
    SAFE_TOOLS, CONFIRM_TOOLS,
)


# ── Layer 2: Modes ────────────────────────────────────

def test_read_tools_always_allowed():
    c = PermissionChecker(PermissionMode.DEFAULT)
    for name in SAFE_TOOLS:
        assert c.check(name, {}).is_allowed

def test_write_needs_confirm_default():
    r = PermissionChecker(PermissionMode.DEFAULT).check("write", {"path": "test.txt"})
    assert r.needs_confirmation

def test_bypass_allows_write():
    assert PermissionChecker(PermissionMode.BYPASS).check("write", {"path": "t.txt"}).is_allowed

def test_accept_edits_allows_write():
    assert PermissionChecker(PermissionMode.ACCEPT_EDITS).check("write", {"path": "t.txt"}).is_allowed

def test_dont_ask_denies_write():
    assert PermissionChecker(PermissionMode.DONT_ASK).check("write", {"path": "t.txt"}).is_denied

def test_plan_denies_write():
    assert PermissionChecker(PermissionMode.PLAN).check("write", {"path": "t.txt"}).is_denied

def test_path_whitelist():
    c = PermissionChecker(PermissionMode.DEFAULT)
    c.confirm_path("src/main.py")
    assert c.check("write", {"path": "src/main.py"}).is_allowed
    assert c.check("write", {"path": "src/other.py"}).needs_confirmation

def test_reset_clears_whitelist():
    c = PermissionChecker(PermissionMode.DEFAULT)
    c.confirm_path("src/main.py")
    c.reset()
    assert c.check("write", {"path": "src/main.py"}).needs_confirmation


# ── Layer 3: Rules ────────────────────────────────────

def test_rules_from_file():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "perms.json")
        json.dump({
            "deny": [{"tool": "write", "path": "*.env", "action": "deny"}],
            "allow": [{"tool": "write", "path": "src/**", "action": "allow"}],
        }, open(p, "w"))
        rules = PermissionRules.from_file(p)
        assert len(rules.deny) == 1
        assert len(rules.allow) == 1

def test_deny_rule_overrides():
    rules = PermissionRules(deny=[PermissionRule(tool="write", path="*.env", action="deny")])
    c = PermissionChecker(PermissionMode.DEFAULT, rules=rules)
    r = c.check("write", {"path": ".env"})
    assert r.is_denied

def test_allow_rule():
    rules = PermissionRules(allow=[PermissionRule(tool="write", path="src/**", action="allow")])
    c = PermissionChecker(PermissionMode.DEFAULT, rules=rules)
    r = c.check("write", {"path": "src/main.py"})
    assert r.is_allowed

def test_ask_rule():
    rules = PermissionRules(ask=[PermissionRule(tool="write", path="*.yaml", action="ask")])
    c = PermissionChecker(PermissionMode.DEFAULT, rules=rules)
    r = c.check("write", {"path": "config.yaml"})
    assert r.needs_confirmation

def test_deny_rule_beats_mode():
    rules = PermissionRules(deny=[PermissionRule(tool="write", path="*.lock", action="deny")])
    c = PermissionChecker(PermissionMode.BYPASS, rules=rules)
    r = c.check("write", {"path": "poetry.lock"})
    assert r.is_denied  # deny rule even beats bypass mode


# ── Layer 5: Path validation ──────────────────────────

def test_validate_protected_env():
    err = validate_path(".env")
    assert err and "Protected" in err

def test_validate_protected_git():
    assert validate_path(".git/config") is not None

def test_validate_outside_workspace():
    set_workspace_boundary("/tmp/ws")
    assert validate_path("/etc/passwd", "/tmp/ws") is not None

def test_validate_inside_workspace():
    assert validate_path("src/main.py", os.getcwd()) is None


if __name__ == "__main__":
    test_read_tools_always_allowed()
    test_write_needs_confirm_default()
    test_bypass_allows_write()
    test_accept_edits_allows_write()
    test_dont_ask_denies_write()
    test_plan_denies_write()
    test_path_whitelist()
    test_reset_clears_whitelist()
    test_rules_from_file()
    test_deny_rule_overrides()
    test_allow_rule()
    test_ask_rule()
    test_deny_rule_beats_mode()
    test_validate_protected_env()
    test_validate_protected_git()
    test_validate_outside_workspace()
    test_validate_inside_workspace()
    print("All permission tests passed!")
