import anthropic
from anthropic.lib.streaming import ContentBlockStopEvent, TextEvent
from anthropic.lib.streaming._types import ThinkingEvent
from anthropic.types import (
    MessageParam,
    RawContentBlockStartEvent,
    ToolUseBlock,
)
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.styled import Styled

from ..cli.display import LIGHT_HINT_STYLE_RICH, print_tool_result, print_tool_start
from ..cli.models import get_max_output_tokens
from ..cli.token import token_tracker
from ..config import WORKDIR, client, config
from .skills import skill_loader
from .tools import TOOL_HANDLERS, TOOLS

console = Console()

TOOLS_LIST = "\n".join(f"- {tool['name']}: {tool['description']}" for tool in TOOLS)

SYSTEM = f"""
You are an expert coding assistant at {WORKDIR}. You help users by reading files, executing commands, editing code, and writing new files.

Available tools:
{TOOLS_LIST}

Available skills:
{skill_loader.get_descriptions()}
"""


def agent_loop(messages: list[MessageParam]) -> None:
    model = config.get_model()
    max_tokens = get_max_output_tokens(model) or 1024

    while True:
        status = console.status("Thinking")
        status.start()

        effort = config.get_reasoning_effort()
        if effort == "disabled":
            thinking_param = None
            output_config = None
        elif effort == "adaptive":
            thinking_param = {"type": "adaptive"}
            output_config = None
        else:
            thinking_param = {"type": "adaptive"}
            output_config = {"effort": effort}

        live: Live | None = None
        try:
            stream_kwargs: dict = {
                "model": model,
                "system": SYSTEM,
                "messages": messages,
                "tools": TOOLS,
                "max_tokens": max_tokens,
            }
            if thinking_param is not None:
                stream_kwargs["thinking"] = thinking_param
                if output_config is not None:
                    stream_kwargs["output_config"] = output_config
            with client.messages.stream(**stream_kwargs) as stream:
                for event in stream:
                    if isinstance(event, RawContentBlockStartEvent):
                        if event.content_block.type in ("thinking", "text"):
                            status.stop()
                            live = Live(console=console, refresh_per_second=15, vertical_overflow="visible")
                            live.start()
                    elif isinstance(event, ThinkingEvent):
                        if live:
                            live.update(Styled(Markdown(event.snapshot), style=LIGHT_HINT_STYLE_RICH))
                    elif isinstance(event, TextEvent):
                        if live:
                            live.update(Markdown(event.snapshot))
                    elif isinstance(event, ContentBlockStopEvent):
                        if live:
                            live.stop()
                            live = None
                            print()
                response = stream.get_final_message()
                status.stop()
        except (TypeError, anthropic.APIStatusError) as e:
            if live:
                live.stop()
            status.stop()
            print(f"Unexpected {e=}\n")
            messages.pop()
            return

        messages.append({"role": "assistant", "content": response.content})
        token_tracker.update(response.usage.input_tokens, response.usage.output_tokens)

        results = []
        working_status = None
        for block in response.content:
            if isinstance(block, ToolUseBlock):
                if working_status is None:
                    working_status = console.status("Working")
                    working_status.start()
                handler = TOOL_HANDLERS.get(block.name)
                print_tool_start(block.name, block.input)
                output = (
                    handler(**block.input) if handler else f"Unknown tool: {block.name}"
                )
                if working_status is not None:
                    working_status.stop()
                    working_status = None
                print_tool_result(block.name, block.input, output)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": output}
                )

        if working_status is not None:
            working_status.stop()

        if response.stop_reason != "tool_use":
            return

        messages.append({"role": "user", "content": results})
