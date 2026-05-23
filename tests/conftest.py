"""Test helpers for workspace-local temporary directories."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def workspace_tmp(request):
    root = Path(".tmp") / "pytest" / request.node.name.replace("/", "_").replace("\\", "_").replace(":", "_")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root.resolve()
    finally:
        if root.exists():
            shutil.rmtree(root)
