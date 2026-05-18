from __future__ import annotations
"""配置热重载测试。"""
import time
import tempfile
import shutil
from pathlib import Path
from src.SmallShrimp.utils.config import Config


def test_deep_merge():
    """测试深度合并。"""
    base = {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}
    override = {"b": {"c": 99, "f": 5}, "g": 6}
    result = Config._deep_merge(base, override)

    assert result == {"a": 1, "b": {"c": 99, "d": 3, "f": 5}, "e": 4, "g": 6}
    print("test_deep_merge PASSED")


def test_load_yaml():
    """测试 YAML 加载。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        config_path.write_text("""
providers:
  openai:
    api_key: test-key
default_provider: openai
""")
        config = Config.from_yaml(config_path)
        assert config.get_default_provider() == "openai"
        assert config.get_provider_config("openai")["api_key"] == "test-key"
        print("test_load_yaml PASSED")


def test_merge_configs():
    """测试合并多个配置文件。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)

        # 创建用户配置
        user_config = workspace / "config.user.yaml"
        user_config.write_text("""
providers:
  deepseek:
    api_key: user-key
default_provider: deepseek
""")

        # 创建运行时配置
        runtime_config = workspace / "config.runtime.yaml"
        runtime_config.write_text("""
default_provider: openai
""")

        # 测试合并加载
        config_data = Config._load_merged_configs(workspace)
        assert config_data["default_provider"] == "openai"  # 运行时覆盖用户
        assert config_data["providers"]["deepseek"]["api_key"] == "user-key"
        print("test_merge_configs PASSED")


def test_reload():
    """测试手动重载。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        config_path.write_text("version: 1")

        config = Config.from_yaml(config_path)
        assert config.data["version"] == 1

        # 修改文件
        config_path.write_text("value: 2")
        config.reload()

        assert config.data["value"] == 2
        print("test_reload PASSED")


def test_on_change_callback():
    """测试变更回调。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "config.yaml"
        config_path.write_text("value: 1")

        config = Config.from_yaml(config_path)
        callback_count = 0

        def on_change(data):
            nonlocal callback_count
            callback_count += 1

        config.on_change(on_change)
        config.reload()

        assert callback_count == 1
        print("test_on_change_callback PASSED")


if __name__ == "__main__":
    test_deep_merge()
    test_load_yaml()
    test_merge_configs()
    test_reload()
    test_on_change_callback()
    print("\nAll tests passed!")