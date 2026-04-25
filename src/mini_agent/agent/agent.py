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
    """Drive live Markdown display from stream events.

    The SDK accumulates events into the final ``Message`` in parallel,
    so this function only handles visual output.
    """

    live: Live | None = None
    block_type: str | None = None
    text = ""

    for event in stream:
        if event.type == "content_block_start":
            block_type = event.content_block.type
            text = ""

        elif event.type == "content_block_delta":
            delta = event.delta
            if delta.type == "text_delta":
                text += delta.text
                if live is None:
                    live = Live(
                        Markdown(""),
                        console=console,
                        refresh_per_second=15,
                        vertical_overflow="visible",
                    )
                    live.start()
                live.update(Markdown(text))
            elif delta.type == "thinking_delta":
                console.print(delta.thinking, end="", style=LIGHT_HINT_STYLE_RICH)
                sys.stdout.flush()

        elif event.type == "content_block_stop":
            if block_type == "text" and live is not None:
                live.stop()
                live = None
                console.print()
            elif block_type == "thinking":
                console.print()
                console.print()
            sys.stdout.flush()

    if live is not None:
        live.stop()


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
