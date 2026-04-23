from pathlib import Path

from ..config import config
from .token import Usage, token_tracker


def _usage_lines(usage: Usage | None) -> list[str]:
    if usage is None:
        return ["Usage: No usage data available"]

    return [
        f"Input: {usage.input_tokens}",
        f"Output: {usage.output_tokens}",
        f"Cache creation: {usage.cache_creation_input_tokens}",
        f"Cache read: {usage.cache_read_input_tokens}",
    ]


def format_status_report(session_id: str) -> str:
    lines = [
        f"Model: {config.get_model()} {config.get_reasoning_effort()}",
        f"Directory: {Path.cwd()}",
        f"Session: {session_id}",
        "",
    ]
    lines.extend(_usage_lines(token_tracker.get()))
    return "\n".join(lines)
