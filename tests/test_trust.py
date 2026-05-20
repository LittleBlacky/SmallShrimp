from __future__ import annotations
"""Trust Dialog 测试。"""
import os, tempfile, json
from pathlib import Path
from src.SmallShrimp.core.trust import TrustManager


def test_new_dir_not_trusted():
    with tempfile.TemporaryDirectory() as d:
        tm = TrustManager()
        assert not tm.is_trusted(d)


def test_trust_persists():
    with tempfile.TemporaryDirectory() as d:
        state = os.path.join(d, "trust.json")
        tm = TrustManager(state_path=state)
        tm.trust("/test/dir")
        assert tm.is_trusted("/test/dir")

        # Reload
        tm2 = TrustManager(state_path=state)
        assert tm2.is_trusted("/test/dir")


def test_scan_dangerous_finds_env():
    with tempfile.TemporaryDirectory() as d:
        # Create a .env file
        Path(os.path.join(d, ".env")).write_text("KEY=value")
        tm = TrustManager()
        warnings = tm.scan_dangerous(d)
        assert ".env" in warnings


def test_scan_dangerous_finds_package_json():
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, ".github", "workflows"))
        Path(os.path.join(d, ".github", "workflows", "ci.yml")).write_text("name: CI")
        tm = TrustManager()
        warnings = tm.scan_dangerous(d)
        assert any(".github" in w for w in warnings)


def test_scan_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        tm = TrustManager()
        warnings = tm.scan_dangerous(d)
        assert warnings == []


def test_check_and_trust_no_callback_auto_trusts():
    with tempfile.TemporaryDirectory() as d:
        state = os.path.join(d, "trust.json")
        tm = TrustManager(state_path=state)
        assert tm.check_and_trust(d)  # No callback → auto-trust
        assert tm.is_trusted(d)


def test_check_and_trust_with_callback_deny():
    with tempfile.TemporaryDirectory() as d:
        Path(os.path.join(d, ".env")).write_text("SECRET=xxx")
        tm = TrustManager()
        # Callback denies
        result = tm.check_and_trust(d, confirm_fn=lambda dir, warnings: False)
        assert not result
        assert not tm.is_trusted(d)


if __name__ == "__main__":
    test_new_dir_not_trusted()
    test_trust_persists()
    test_scan_dangerous_finds_env()
    test_scan_dangerous_finds_package_json()
    test_scan_empty_dir()
    test_check_and_trust_no_callback_auto_trusts()
    test_check_and_trust_with_callback_deny()
    print("All trust tests passed!")
