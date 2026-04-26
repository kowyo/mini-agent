import sys
from typing import cast

import anthropic
import anthropic.lib.streaming
from anthropic.types import ContentBlockDeltaEvent, TextDelta, ThinkingDelta
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from .theme import LIGHT_HINT_STYLE_RICH

console = Console()


def display_stream_events(stream: anthropic.lib.streaming.MessageStream) -> None:
    """Drive live Markdown display from stream events.

    The SDK accumulates events into the final ``Message`` in parallel,
    so this function only handles visual output.
    """

    live: Live | None = None
    text = ""

    for event in stream:
        if event.type == "content_block_start":
            text = ""

        elif event.type == "content_block_delta":
            delta = cast(ContentBlockDeltaEvent, event).delta
            if isinstance(delta, TextDelta):
                chunk, style = delta.text, None
            elif isinstance(delta, ThinkingDelta):
                chunk, style = delta.thinking, LIGHT_HINT_STYLE_RICH
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

        elif event.type == "content_block_stop" and live is not None:
            live.stop()
            live = None
            console.print()
            sys.stdout.flush()

    if live is not None:
        live.stop()
