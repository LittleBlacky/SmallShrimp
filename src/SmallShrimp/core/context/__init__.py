__all__ = [
    "ContextEngine",
    "ContextGuard",
    "PromptBuilder",
    "Context",
    "SharedContext",
    "create_context_engine",
]


def __getattr__(name: str):
    if name in {"Context", "SharedContext"}:
        from ...server.context import Context

        return Context
    if name in {"ContextEngine", "create_context_engine"}:
        from .context_engine import ContextEngine, create_context_engine

        return {
            "ContextEngine": ContextEngine,
            "create_context_engine": create_context_engine,
        }[name]
    if name == "ContextGuard":
        from .context_guard import ContextGuard

        return ContextGuard
    if name == "PromptBuilder":
        from .prompt_builder import PromptBuilder

        return PromptBuilder
    raise AttributeError(name)
