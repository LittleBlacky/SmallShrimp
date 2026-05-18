from __future__ import annotations
"""配置管理模块。"""
from pathlib import Path
from typing import Any, Callable, Optional
import yaml
from .config_reloader import ConfigReloader


class Config:
    """配置类，支持热重载。"""

    def __init__(self, data: dict[str, Any], workspace: Path | None = None) -> None:
        self.data = data
        self._workspace = workspace or Path(".")
        self._reloader: Optional[ConfigReloader] = None
        self._on_change_callbacks: list[Callable[[dict[str, Any]], None]] = []

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path) as f:
            data = yaml.safe_load(f)
        workspace = path.parent
        config = cls(data, workspace)
        config._config_file = path  # 存储原始文件路径用于 reload
        return config

    @classmethod
    def _load_merged_configs(cls, workspace_dir: Path) -> dict[str, Any]:
        """加载并深度合并所有配置文件。

        加载顺序（后面的覆盖前面的）：
        1. config.user.yaml - 用户配置
        2. config.runtime.yaml - 运行时配置（可选）
        """
        config_data: dict[str, Any] = {}

        user_config = workspace_dir / "config.user.yaml"
        if user_config.exists():
            with open(user_config) as f:
                config_data = cls._deep_merge(config_data, yaml.safe_load(f) or {})

        runtime_config = workspace_dir / "config.runtime.yaml"
        if runtime_config.exists():
            with open(runtime_config) as f:
                config_data = cls._deep_merge(config_data, yaml.safe_load(f) or {})

        return config_data

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """深度合并两个字典，override 覆盖 base。"""
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = Config._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def reload(self) -> bool:
        """重新加载配置文件。"""
        try:
            config_file = getattr(self, '_config_file', None)
            if config_file and config_file.exists():
                with open(config_file) as f:
                    self.data = yaml.safe_load(f) or {}
            else:
                config_data = self._load_merged_configs(self._workspace)
                self.data = config_data

            # 触发变更回调
            for callback in self._on_change_callbacks:
                callback(self.data)

            return True
        except Exception:
            return False

    def on_change(self, callback: Callable[[dict[str, Any]], None]) -> None:
        """注册配置变更回调。"""
        self._on_change_callbacks.append(callback)

    def start_auto_reload(self, on_reload: Optional[callable] = None) -> None:
        """启动自动热重载。"""
        if self._reloader is not None:
            return

        def handle_reload():
            self.reload()
            if on_reload:
                on_reload()

        self._reloader = ConfigReloader(self._workspace, handle_reload)
        self._reloader.start()

    def stop_auto_reload(self) -> None:
        """停止自动热重载。"""
        if self._reloader is not None:
            self._reloader.stop()
            self._reloader = None

    def get_provider_config(self, name: str) -> dict[str, Any]:
        """获取指定 provider 的配置。"""
        providers = self.data.get("providers", {})
        return providers.get(name, {})

    def get_default_provider(self) -> str:
        """获取默认 provider 名称。"""
        return self.data.get("default_provider", "")

    @property
    def workspace(self) -> Path:
        return self._workspace

    @workspace.setter
    def workspace(self, path: Path) -> None:
        self._workspace = path