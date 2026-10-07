import sys
from collections.abc import Iterable

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from ...agent.providers.types import (
    BlockStart,
    BlockStop,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
)
from .theme import THINKING_STYLE_RICH

console = Console()


def display_stream_events(stream: Iterable[StreamEvent]) -> None:
    """Render live Markdown from provider-neutral stream events."""

    live: Live | None = None
    text = ""

    try:
        for event in stream:
            if isinstance(event, BlockStart):
                text = ""
                continue
            if isinstance(event, TextDelta):
                chunk, style = event.text, None
            elif isinstance(event, ThinkingDelta):
                chunk, style = event.text, THINKING_STYLE_RICH
            elif isinstance(event, BlockStop):
                if live is not None:
                    live.stop()
                    live = None
                    console.print()
                    sys.stdout.flush()
                continue
            else:
                continue
            text += chunk
            if live is None:
                live = Live(
                    Markdown(""),
                    console=console,
                    refresh_per_second=15,
                )
                live.start()
            live.update(Markdown(text, style=style or ""))
    finally:
        if live is not None:
            live.stop()
