# Project Structure

SmallShrimp is a multi-endpoint, continuously evolving personal assistant Agent. The repository is split into stable product code, runtime data, optional apps, and local reference material.

## Top-Level Layout

```text
SmallShrimp/
├── src/SmallShrimp/              # Python package
├── tests/                        # pytest suite
├── docs/                         # project documentation
├── apps/
│   └── desktop/                  # Electron desktop app
├── examples/
│   └── default_workspace/        # example workspace config
├── workspace/                    # local runtime workspace
├── benchmarks/                   # benchmark scripts and reports
├── scripts/                      # maintenance scripts
├── references/                   # local external reference projects, ignored by git
├── assets/                       # local screenshots/assets
├── pyproject.toml                # Python package metadata
├── pytest.ini                    # pytest configuration
└── README.md
```

## Python Package Layout

```text
src/SmallShrimp/
├── cli/                          # Typer CLI entry points
├── core/                         # agent runtime and orchestration
│   ├── runtime/                  # Agent, AgentSession, messages, turn/session state
│   ├── context/                  # prompt building, context windows, compaction
│   ├── security/                 # permissions, trust, sandbox, shell guardrails
│   ├── definitions/              # Agent/Cron/Skill definition loading
│   ├── events/                   # event types, event bus, routing, worker base
│   ├── learning/                 # correction, reflection, pattern/failure learning
│   ├── commands/                 # slash command handlers
│   └── memory/                   # memory pipeline, stores, searchers
├── tools/                        # built-in tool implementations and registry
├── provider/                     # LLM, web search, and web read providers
├── channels/                     # chat/channel adapters
├── server/                       # FastAPI server and workers
└── utils/                        # config and definition loading helpers
```

## Boundaries

- `src/SmallShrimp/` contains importable runtime code.
- `src/SmallShrimp/core/*.py` compatibility modules re-export the new subpackage locations, so older imports continue to work while new code can target the clearer subpackages.
- `tests/` mirrors feature areas with focused test modules.
- `apps/desktop/` is the frontend app and should not import Python internals directly except through defined server/API boundaries.
- `workspace/` is runtime state. Do not commit user config, sessions, memories, cache, or credentials.
- `examples/default_workspace/` is safe example configuration.
- `references/` is for copied external projects used as design references. It is intentionally ignored by git.
- `assets/screenshots/` is for local screenshots and other bulky inspection artifacts.

## Refactoring Rule

Prefer moving one layer at a time:

1. Keep Python package imports stable under `src/SmallShrimp/`.
2. Move external or optional material before moving runtime modules.
3. Update docs and path references in the same change as any directory move.
4. Run focused tests for the touched layer before broader test runs.
