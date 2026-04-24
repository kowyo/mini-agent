from collections.abc import Sequence

from rich.console import Console
from rich.text import Text

from .theme import LIGHT_HINT_STYLE_RICH


def print_box(console: Console, lines: Sequence[str | Text]) -> None:
    width = max(
        len(line.plain) if isinstance(line, Text) else len(line) for line in lines
    )
    top = f"╭{'─' * (width + 2)}╮"
    bottom = f"╰{'─' * (width + 2)}╯"
    console.print(Text(top, style=LIGHT_HINT_STYLE_RICH))
    for line in lines:
        display_line: str | Text
        if isinstance(line, Text):
            display_line = line.copy()
            padding = width - len(line.plain)
            if padding > 0:
                display_line.append(" " * padding)
        else:
            display_line = line.ljust(width)
        console.print(
            Text("│ ", style=LIGHT_HINT_STYLE_RICH),
            display_line,
            Text(" │", style=LIGHT_HINT_STYLE_RICH),
            sep="",
        )
    console.print(Text(bottom, style=LIGHT_HINT_STYLE_RICH))
