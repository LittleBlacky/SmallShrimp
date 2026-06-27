"""Message sanitization pipeline — clean inputs before LLM calls.

Three sanitizers:
  1. Strip surrogate characters from user input
  2. Repair empty/missing tool call arguments to {}
  3. Repair message alternation (ensure user/assistant alternation)
"""
from __future__ import annotations

import json
import re
from typing import Any


def sanitize_user_message(text: str) -> str:
    """Remove surrogate characters that would break UTF-8 encoding."""
    if not text:
        return text
    # Remove lone surrogates (U+D800–U+DFFF)
    return re.sub(r'[\ud800-\udfff]', '', text)


def sanitize_tool_result(text: str) -> str:
    """Remove surrogate characters from tool results."""
    if not text:
        return text
    return re.sub(r'[\ud800-\udfff]', '', text)


def repair_tool_call_args(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure every tool call has valid JSON arguments.

    Empty or None arguments → "{}"
    String arguments that aren't valid JSON → "{}"
    """
    for tc in tool_calls:
        func = tc.get("function", {})
        args = func.get("arguments")
        if args is None or args == "":
            func["arguments"] = "{}"
        elif isinstance(args, str):
            try:
                json.loads(args)
            except (json.JSONDecodeError, ValueError):
                func["arguments"] = "{}"
    return tool_calls


def repair_message_alternation(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure user/assistant alternation in the message list.

    Consecutive same-role messages (except system/tool) are merged.
    Tool messages are kept in place (they follow assistant tool_calls).
    """
    if not messages:
        return messages

    result: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "")

        # System and tool messages pass through as-is
        if role in ("system", "tool"):
            result.append(msg)
            continue

        # Check if previous non-system, non-tool message has the same role
        if result and role in ("user", "assistant"):
            prev = result[-1]
            prev_role = prev.get("role", "")
            if prev_role == role:
                # Merge: append content to previous
                prev_content = prev.get("content") or ""
                curr_content = msg.get("content") or ""
                if prev_content and curr_content:
                    prev["content"] = prev_content + "\n\n" + curr_content
                elif curr_content:
                    prev["content"] = curr_content
                # Preserve tool_calls from the later message
                if msg.get("tool_calls"):
                    prev["tool_calls"] = msg["tool_calls"]
                continue

        result.append(msg)

    return result
