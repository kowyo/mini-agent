import shutil
from pathlib import Path

from rich.style import Style
from rich.text import Text

from ..agent.skills import skill_loader
from ..agent.system_prompt import context_files as loaded_context_files
from ..config import config
from .display.theme import ACCENT_COLOR
from .models import get_max_context_tokens
from .token import Usage, token_tracker


def format_usage_report(usage: Usage | None) -> list[Text]:
    if usage is None:
        return []

    t = Text("Token Usage:", style="bold")
    lines: list[Text] = [t]

    rows = [
        ("Input:          ", f"{usage.input_tokens}"),
        ("Output:         ", f"{usage.output_tokens}"),
        ("Cache Creation: ", f"{usage.cache_creation_input_tokens}"),
        ("Cache Read:     ", f"{usage.cache_read_input_tokens}"),
    ]
    for label, value in rows:
        line = Text()
        line.append(label)
        line.append(value, style=ACCENT_COLOR)
        lines.append(line)

    return lines


def _format_context_window(usage: Usage | None) -> Text | None:
    context_limit = get_max_context_tokens(config.get_model())
    if context_limit is None:
        return None

    last_round = token_tracker.get_last_round()
    if last_round is not None:
        used = last_round.total_input_tokens + last_round.output_tokens
    else:
        used = 0

    text = Text("Context window: ", style="bold")
    text.append(
        f"{used:,} / {context_limit:,} ({used / context_limit:.1%})",
        style=Style(color=ACCENT_COLOR, bold=False),
    )
    return text


def format_status_report(session_id: str) -> list[str | Text]:
    terminal_width = shutil.get_terminal_size().columns
    max_content_width = terminal_width - 4

    usage = token_tracker.get()
    usage_report = format_usage_report(usage)
    lines: list[str | Text] = []

    status_items = [
        ("Model:          ", f"{config.get_model()} {config.get_reasoning_effort()}"),
        ("Directory:      ", str(Path.cwd())),
        ("Session:        ", session_id),
    ]

    any_split = any(
        len(f"{label}{value}") > max_content_width for label, value in status_items
    )

    for label, value in status_items:
        if any_split:
            lines.append(Text(label.rstrip(), style="bold"))
            lines.append(Text(value))
        else:
            t = Text()
            t.append(label.rstrip(), style="bold")
            padding = len(label) - len(label.rstrip())
            if padding:
                t.append(" " * padding)
            t.append(value)
            lines.append(t)

    if loaded_context_files:
        lines.append("")
        lines.append(Text("Context:", style="bold"))
        cwd = Path.cwd()
        home = Path.home()
        for path in loaded_context_files:
            try:
                item = str(path.relative_to(cwd))
            except ValueError:
                try:
                    item = f"~/{path.relative_to(home)}"
                except ValueError:
                    item = str(path)
            lines.append(Text(f"- {item}"))

    if skill_loader.skills:
        lines.append("")
        lines.append(Text("Skills:", style="bold"))
        for skill in skill_loader.skills:
            lines.append(Text(f"- {skill}"))

    context_line = _format_context_window(usage)
    if context_line:
        lines.append("")
        lines.append(context_line)

    if usage_report:
        lines.append("")
        lines.extend(usage_report)

    return lines
