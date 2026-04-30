import shutil
from collections.abc import Sequence

from rich.console import Console
from rich.text import Text

from .theme import LIGHT_HINT_STYLE_RICH


def print_box(console: Console, lines: Sequence[str | Text]) -> None:
    terminal_width = shutil.get_terminal_size().columns
    # Max content width = terminal width - 4 (for "│ " and " │")
    max_content_width = terminal_width - 4
    content_width = max(
        len(line.plain) if isinstance(line, Text) else len(line) for line in lines
    )
    width = min(content_width, max_content_width)
    top = f"╭{'─' * (width + 2)}╮"
    bottom = f"╰{'─' * (width + 2)}╯"
    console.print(Text(top, style=LIGHT_HINT_STYLE_RICH), highlight=False)
    for line in lines:
        if isinstance(line, Text):
            display = line.copy()
            while len(display.plain) > width:
                chunk = display[:width]
                display = display[width:]
                padded = chunk.copy()
                padded.append(" " * (width - len(chunk.plain)))
                console.print(
                    Text("│ ", style=LIGHT_HINT_STYLE_RICH),
                    padded,
                    Text(" │", style=LIGHT_HINT_STYLE_RICH),
                    sep="",
                    highlight=False,
                )
            padding = width - len(display.plain)
            if padding > 0:
                display.append(" " * padding)
            console.print(
                Text("│ ", style=LIGHT_HINT_STYLE_RICH),
                display,
                Text(" │", style=LIGHT_HINT_STYLE_RICH),
                sep="",
                highlight=False,
            )
        else:
            plain = line
            while len(plain) > width:
                chunk = plain[:width]
                plain = plain[width:]
                console.print(
                    Text("│ ", style=LIGHT_HINT_STYLE_RICH),
                    chunk.ljust(width),
                    Text(" │", style=LIGHT_HINT_STYLE_RICH),
                    sep="",
                    highlight=True,
                )
            console.print(
                Text("│ ", style=LIGHT_HINT_STYLE_RICH),
                plain.ljust(width),
                Text(" │", style=LIGHT_HINT_STYLE_RICH),
                sep="",
                highlight=True,
            )
    console.print(Text(bottom, style=LIGHT_HINT_STYLE_RICH), highlight=False)
