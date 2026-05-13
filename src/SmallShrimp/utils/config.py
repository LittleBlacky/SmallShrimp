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
    
    def get_llm_config(self) -> dict[str, Any]:
        return self.data.get("llm", {})
    
    @property
    def workspace(self) -> Path:
        return self._workspace
    
    @workspace.setter
    def workspace(self, path: Path) -> None:
        self._workspace = path