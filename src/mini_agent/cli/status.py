from pathlib import Path

from rich.text import Text

from ..config import config
from .display.theme import ACCENT_COLOR
from .models import get_max_context_tokens
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


def _format_context_window(usage: Usage | None) -> Text | None:
    context_limit = get_max_context_tokens(config.get_model())
    if context_limit is None:
        return None

    last_round = token_tracker.get_last_round()
    if last_round is not None:
        used = last_round.total_input_tokens + last_round.output_tokens
    else:
        used = 0

    text = Text("Context window: ")
    text.append(f"{used:,}", style=ACCENT_COLOR)
    text.append(" / ")
    text.append(f"{context_limit:,}", style=ACCENT_COLOR)
    text.append(" (")
    text.append(f"{used / context_limit:.1%}", style=ACCENT_COLOR)
    text.append(")")
    return text


def format_status_report(session_id: str) -> list[str | Text]:
    usage = token_tracker.get()
    usage_report = format_usage_report(usage)
    lines: list[str | Text] = [
        f"Model:          {config.get_model()} {config.get_reasoning_effort()}",
        f"Directory:      {Path.cwd()}",
        f"Session:        {session_id}",
    ]

    context_line = _format_context_window(usage)
    if context_line:
        lines.append("")
        lines.append(context_line)

    if usage_report:
        lines.append("")
        lines.extend(usage_report.splitlines())

    return lines
