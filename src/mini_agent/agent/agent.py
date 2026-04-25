import sys
from datetime import date

import anthropic
from anthropic.types import (
    MessageParam,
    ToolUseBlock,
)
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

from ..cli.display import LIGHT_HINT_STYLE_RICH, print_tool_result, print_tool_start
from ..cli.models import get_max_output_tokens
from ..cli.token import Usage, token_tracker
from ..config import WORKDIR, client, config
from .skills import skill_loader
from .tools import TOOL_HANDLERS, TOOLS

console = Console()

TOOLS_LIST = "\n".join(f"- {tool['name']}: {tool['description']}" for tool in TOOLS)

_SYSTEM_BASE = f"""You are an expert coding assistant. You help users by reading files, executing commands, editing code, and writing new files.

Available tools:
{TOOLS_LIST}
"""

SYSTEM = _SYSTEM_BASE
if skill_loader.skills:
    SYSTEM += f"\nAvailable skills:\n{skill_loader.get_descriptions()}\n"
SYSTEM += (
    f"\nCurrent date: {date.today().isoformat()}\nCurrent working directory: {WORKDIR}"
)


def _display_stream_events(stream: anthropic.lib.streaming.MessageStream) -> None:
    """Iterate stream events solely to drive live display.

    The SDK's ``MessageStream`` accumulates events into the final
    ``Message`` internally (via ``accumulate_event``) as each event is
    yielded, so we only handle visual output here.  The properly
    constructed response is obtained later with ``get_final_message()``.
    """

    live_display: Live | None = None
    current_block_type: str | None = None
    current_text = ""

    def _stop_live() -> None:
        nonlocal live_display
        if live_display is not None:
            live_display.stop()
            live_display = None

    for event in stream:
        if event.type == "content_block_start":
            cb = event.content_block
            current_block_type = cb.type

            if cb.type != "text":
                _stop_live()
            else:
                current_text = ""

        elif event.type == "content_block_delta":
            delta = event.delta

            if delta.type == "text_delta":
                current_text += delta.text
                if live_display is None:
                    _stop_live()
                    live_display = Live(
                        Markdown(""),
                        console=console,
                        refresh_per_second=15,
                        vertical_overflow="visible",
                    )
                    live_display.start()
                if live_display is not None:
                    live_display.update(Markdown(current_text))

            elif delta.type == "thinking_delta":
                # Print raw text — wrapping each delta in Markdown() causes
                # Rich to emit unwanted newlines per chunk.
                console.print(
                    delta.thinking,
                    end="",
                    style=LIGHT_HINT_STYLE_RICH,
                )
                sys.stdout.flush()

        elif event.type == "content_block_stop":
            if current_block_type == "text":
                _stop_live()
                console.print()  # blank line after text block
            elif current_block_type == "thinking":
                console.print()  # newline after streaming thinking

            current_block_type = None

    _stop_live()


def agent_loop(messages: list[MessageParam]) -> None:
    model = config.get_model()
    max_tokens = get_max_output_tokens(model) or 32768

    working_status = None
    thinking_status = None

    try:
        while True:
            working_status = None
            thinking_status = console.status("Thinking")
            thinking_status.start()

            effort = config.get_reasoning_effort()
            if effort == "disabled":
                thinking_param = None
                output_config = None
            elif effort == "adaptive":
                thinking_param = {"type": "adaptive", "display": "summarized"}
                output_config = None
            else:
                thinking_param = {"type": "adaptive", "display": "summarized"}
                output_config = {"effort": effort}

            try:
                stream_kwargs: dict = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "system": SYSTEM,
                    "messages": messages,
                    "tools": TOOLS,
                }
                if "claude" in model.lower():
                    stream_kwargs["cache_control"] = {"type": "ephemeral"}
                if thinking_param is not None:
                    stream_kwargs["thinking"] = thinking_param
                    if output_config is not None:
                        stream_kwargs["output_config"] = output_config

                with client.messages.stream(**stream_kwargs) as stream:
                    thinking_status.stop()

                    # Drive live display from stream events.
                    # The SDK accumulates into the final Message in parallel.
                    _display_stream_events(stream)

                    # Obtain the properly SDK-built response.
                    response = stream.get_final_message()

            except (TypeError, anthropic.APIStatusError) as e:
                thinking_status.stop()
                print(f"Unexpected {e=}\n")
                messages.pop()
                return

            messages.append({"role": "assistant", "content": response.content})
            usage = response.usage
            cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            token_tracker.update(
                Usage(
                    input_tokens=usage.input_tokens or 0,
                    cache_creation_input_tokens=cache_create,
                    cache_read_input_tokens=cache_read,
                    output_tokens=usage.output_tokens,
                )
            )

            results = []
            for block in response.content:
                if isinstance(block, ToolUseBlock):
                    if working_status is None:
                        working_status = console.status("Working")
                        working_status.start()
                    handler = TOOL_HANDLERS.get(block.name)
                    print_tool_start(block.name, block.input)
                    output = (
                        handler(**block.input)
                        if handler
                        else f"Unknown tool: {block.name}"
                    )
                    if working_status is not None:
                        working_status.stop()
                        working_status = None
                    print_tool_result(block.name, block.input, output)
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                        }
                    )

            if working_status is not None:
                working_status.stop()

            if response.stop_reason != "tool_use":
                return

            messages.append({"role": "user", "content": results})

    except KeyboardInterrupt:
        console.print(
            "[bold yellow]■ Conversation interrupted - tell the model what to do differently[/bold yellow]"
        )
        if thinking_status is not None:
            thinking_status.stop()
        if working_status is not None:
            working_status.stop()
        print()
