from pathlib import Path
from typing import Any
import yaml

class Config:

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self._workspace = Path(".")
    
    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(data)
    
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