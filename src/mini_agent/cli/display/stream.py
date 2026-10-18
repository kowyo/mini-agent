import sys
from collections.abc import Iterable

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from ...agent.api.base import BlockEnd, StreamEvent, TextDelta, ThinkingDelta
from .theme import THINKING_STYLE_RICH

_console = Console()


def display_stream_events(stream: Iterable[StreamEvent]) -> None:
    live: Live | None = None
    text = ""

    try:
        for event in stream:
            if isinstance(event, TextDelta):
                chunk, style = event.text, None
            elif isinstance(event, ThinkingDelta):
                chunk, style = event.text, THINKING_STYLE_RICH
            elif isinstance(event, BlockEnd):
                if live is not None:
                    live.stop()
                    live = None
                    _console.print()
                    sys.stdout.flush()
                text = ""
                continue
            else:
                continue

            text += chunk
            if live is None:
                live = Live(
                    Markdown(""),
                    console=_console,
                    refresh_per_second=15,
                )
                live.start()
            live.update(Markdown(text, style=style or ""))
    finally:
        if live is not None:
            live.stop()
