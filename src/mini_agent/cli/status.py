from pathlib import Path

from ..config import config
from .token import Usage, token_tracker


def format_usage_report(usage: Usage | None) -> str:
    if usage is None:
        return ""

    return "\n".join(
        [
            "Token usage:",
            f"Input:          {usage.input_tokens}",
            f"Output:         {usage.output_tokens}",
            f"Cache creation: {usage.cache_creation_input_tokens}",
            f"Cache read:     {usage.cache_read_input_tokens}",
        ]
    )


def format_status_report(session_id: str) -> list[str]:
    usage_report = format_usage_report(token_tracker.get())
    lines = [
        f"Model:          {config.get_model()} {config.get_reasoning_effort()}",
        f"Directory:      {Path.cwd()}",
        f"Session:        {session_id}",
        "",
    ]
    if usage_report:
        lines.extend(usage_report.splitlines())
    return lines
