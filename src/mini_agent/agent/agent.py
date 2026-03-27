import anthropic
from anthropic.types import (
    MessageParam,
    RawContentBlockDeltaEvent,
    TextDelta,
    ThinkingDelta,
    ToolUseBlock,
)
from rich.console import Console

from ..cli.display import print_tool_result
from ..cli.models import get_max_output_tokens
from ..cli.token import token
from ..config import WORKDIR, client, get_model
from ..exceptions import APIKeyMissingError
from .skills import SKILL_LOADER
from .tools import TOOL_HANDLERS, TOOLS

_console = Console()

TOOLS_LIST = "\n".join(f"- {tool['name']}: {tool['description']}" for tool in TOOLS)

SYSTEM = f"""
You are an expert coding assistant at {WORKDIR}. You help users by reading files, executing commands, editing code, and writing new files.

Available tools:
{TOOLS_LIST}

Available skills:
{SKILL_LOADER.get_descriptions()}
"""


def agent_loop(messages: list[MessageParam]) -> None:
    rounds_since_todo = 0
    model = get_model()
    max_tokens = get_max_output_tokens(model) or 1024

    while True:
        status = _console.status("Thinking")
        status.start()
        thinking_started = False
        text_started = False

        try:
            with client.messages.stream(
                model=model,
                system=SYSTEM,
                messages=messages,
                tools=TOOLS,
                max_tokens=max_tokens,
                thinking={"type": "enabled", "budget_tokens": 6000},
            ) as stream:
                for event in stream:
                    if isinstance(event, RawContentBlockDeltaEvent):
                        if (
                            isinstance(event.delta, ThinkingDelta)
                            and event.delta.thinking
                        ):
                            if not thinking_started:
                                status.stop()
                                thinking_started = True
                            print(event.delta.thinking.rstrip(), end="", flush=True)
                        elif isinstance(event.delta, TextDelta) and event.delta.text:
                            if not text_started:
                                status.stop()
                                if thinking_started:
                                    print("\n", flush=True)
                                text_started = True
                            print(event.delta.text, end="", flush=True)
                response = stream.get_final_message()
        except (TypeError, anthropic.APIStatusError) as e:
            status.stop()
            if isinstance(
                e, TypeError
            ) and "Could not resolve authentication method" in str(e):
                print(f"Error: {APIKeyMissingError()}\n")
            else:
                print(f"Error: {e}\n")
            messages.pop()
            return

        if text_started or thinking_started:
            print("\n")
        else:
            status.stop()

        messages.append({"role": "assistant", "content": response.content})
        token.update(response.usage.input_tokens, response.usage.output_tokens)

        used_todo = False
        results = []
        for block in response.content:
            if isinstance(block, ToolUseBlock):
                handler = TOOL_HANDLERS.get(block.name)
                output = (
                    handler(**block.input) if handler else f"Unknown tool: {block.name}"
                )
                print_tool_result(block.name, block.input, output)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": output}
                )
                if block.name == "todo":
                    used_todo = True

        if response.stop_reason != "tool_use":
            return

        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            results.insert(
                0,
                {"type": "text", "text": "<reminder>Update your todos.</reminder>"},
            )

        messages.append({"role": "user", "content": results})
