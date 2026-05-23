# Repository Guidelines

## Project Structure & Module Organization

SmallShrimp is a Python 3.11+ AI agent framework packaged from `src/SmallShrimp`. Core agent behavior lives in `src/SmallShrimp/core`, CLI entry points in `src/SmallShrimp/cli`, provider integrations in `src/SmallShrimp/provider`, channel adapters in `src/SmallShrimp/channels`, server workers in `src/SmallShrimp/server`, and built-in tools in `src/SmallShrimp/tools`. Tests are flat pytest modules in `tests/` named by feature, such as `test_memory.py` and `test_tool_registry.py`. Runtime examples and user data live under `workspace/`, including `agents/`, `skills/`, `crons/`, `sessions/`, and `memories/`.

## Build, Test, and Development Commands

- `python -m venv .venv` then `.\.venv\Scripts\Activate.ps1`: create and activate a local environment on Windows.
- `pip install -e .`: install the package and expose the `smallshrimp` console script.
- `smallshrimp chat`: run the interactive CLI using workspace configuration.
- `python -m src.SmallShrimp.cli.chat`: alternate direct module entry used by existing notes.
- `pytest`: run the full test suite configured by `pytest.ini`.
- `pytest tests/test_memory.py`: run a focused test file while iterating.
- `python -m build`: build distribution artifacts when the `build` package is installed.

## Coding Style & Naming Conventions

Use standard Python style with 4-space indentation, type hints where helpful, and small async functions for tool and worker code. Keep modules and functions in `snake_case`, classes in `PascalCase`, and constants in `UPPER_SNAKE_CASE`. Match nearby patterns before introducing abstractions. Prefer dataclasses or Pydantic models for structured messages/configuration, as used in core modules. No formatter is declared in `pyproject.toml`; keep imports tidy and formatting consistent with existing files.

## Testing Guidelines

Tests use `pytest` and are discovered from files matching `tests/test_*.py`. Add or update focused tests beside related coverage, for example `tests/test_skill_loader.py` for skill loading changes. Use descriptive test names like `test_recall_memory_ranks_recent_entries`. Prefer isolated temporary paths and mocks over writing to real `workspace/` state. Run a targeted test first, then `pytest` before submitting changes.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit-style subjects, often in Chinese, such as `feat: 添加 ...`. Follow `type: concise summary` with types like `feat`, `fix`, `test`, `docs`, or `refactor`. Keep commits scoped to one logical change. Pull requests should include purpose, implementation notes, tests run, linked issues, and screenshots or terminal output for CLI/user-facing behavior.

## Security & Configuration Tips

Do not commit API keys, tokens, session histories, or personal memories from `workspace/`. Keep user-specific provider settings in `workspace/config.user.yaml` or local runtime config files. When touching file, shell, or web tools, preserve guardrails and add tests for permission boundaries.

