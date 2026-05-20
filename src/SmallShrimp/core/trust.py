"""Trust Dialog — prevent auto-execution of hooks from untrusted projects.

Layer 1 of 7-layer defense: when an agent first enters a directory,
scan for potentially dangerous files and ask the user to confirm trust.

Mirrors Claude Code's trust dialog: on first use of a project directory,
warn about hooks, scripts, and automation that could run without user
knowledge.
"""
from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Files that indicate potentially dangerous automation
_DANGEROUS_PATTERNS = [
    ".claude/settings.json",
    ".claude/hooks/**",
    ".github/workflows/**",
    "Makefile",
    "justfile",
    "Taskfile.yml",
    "package.json",       # scripts + postinstall
    ".pre-commit-config.yaml",
    ".husky/**",
    "scripts/**",
    ".env", ".env.*",
    "docker-compose.yml", "docker-compose.yaml",
    "Dockerfile",
]

TrustFn = Callable[[str, list[str]], "bool | None"]  # (dir, warnings) → True/False


@dataclass
class TrustEntry:
    path: str
    trusted_at: str = ""


class TrustManager:
    """Manage trusted directories and scan for dangerous files."""

    def __init__(self, state_path: str | None = None):
        self._state_path = state_path
        self._trusted: dict[str, TrustEntry] = {}
        self._load()

    def is_trusted(self, directory: str) -> bool:
        abspath = str(Path(directory).resolve())
        return abspath in self._trusted

    def trust(self, directory: str) -> None:
        from datetime import datetime, timezone
        abspath = str(Path(directory).resolve())
        self._trusted[abspath] = TrustEntry(
            path=abspath,
            trusted_at=datetime.now(timezone.utc).isoformat(),
        )
        self._save()

    def scan_dangerous(self, directory: str) -> list[str]:
        """Scan for potentially dangerous files. Returns list of warnings."""
        base = Path(directory).resolve()
        warnings: list[str] = []
        for pattern in _DANGEROUS_PATTERNS:
            matches = list(base.glob(pattern))
            for m in matches:
                rel = str(m.relative_to(base))
                warnings.append(rel)
        return sorted(warnings)[:20]  # Cap at 20

    def check_and_trust(
        self, directory: str, confirm_fn: TrustFn | None = None
    ) -> bool:
        """Check trust. If untrusted, scan and ask user. Returns True if OK."""
        if self.is_trusted(directory):
            return True

        warnings = self.scan_dangerous(directory)

        if not confirm_fn:
            # No callback → auto-trust
            self.trust(directory)
            return True

        approved = confirm_fn(directory, warnings)
        if approved:
            self.trust(directory)
            return True
        return False

    def _load(self) -> None:
        if not self._state_path or not os.path.exists(self._state_path):
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                self._trusted[k] = TrustEntry(**v)
        except Exception:
            pass

    def _save(self) -> None:
        if not self._state_path:
            return
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            data = {}
            for k, v in self._trusted.items():
                data[k] = {"path": v.path, "trusted_at": v.trusted_at}
            with open(self._state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
