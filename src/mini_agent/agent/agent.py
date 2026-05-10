import anthropic
from anthropic.types import (
    MessageParam,
    ToolUseBlock,
)
from rich.console import Console
from rich.status import Status

from ..cli.display import display_stream_events, print_tool_result, print_tool_start
from ..cli.models import get_max_output_tokens
from ..cli.token import Usage, token_tracker
from ..config import client, config
from .system_prompt import SYSTEM
from .tools import TOOL_HANDLERS, TOOLS, BashInterruptedError

console = Console()


def agent_loop(messages: list[MessageParam]) -> None:
    model = config.get_model()
    max_tokens = get_max_output_tokens(model) or 32768

    working_status: Status | None = None
    thinking_status: Status | None = None

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
                    display_stream_events(stream)
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
                    input_tokens=usage.input_tokens,
                    cache_creation_input_tokens=cache_create,
                    cache_read_input_tokens=cache_read,
                    output_tokens=usage.output_tokens,
                )
            )

            results = []
            try:
                for block in response.content:
                    if isinstance(block, ToolUseBlock):
                        if working_status is None:
                            working_status = console.status("Working")
                            working_status.start()
                        handler = TOOL_HANDLERS.get(block.name)
                        print_tool_start(block.name, block.input)
                        interrupted = False
                        try:
                            output = (
                                handler(**block.input)
                                if handler
                                else f"Unknown tool: {block.name}"
                            )
                        except BashInterruptedError as e:
                            output = e.partial_output
                            interrupted = True
                        if working_status is not None:
                            working_status.stop()
                            working_status = None
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": output,
                            }
                        )
                        print_tool_result(block.name, block.input, output)
                        if interrupted:
                            raise KeyboardInterrupt
            except KeyboardInterrupt:
                completed_ids = {r["tool_use_id"] for r in results}
                for remaining in response.content:
                    if (
                        isinstance(remaining, ToolUseBlock)
                        and remaining.id not in completed_ids
                    ):
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": remaining.id,
                                "content": "Command aborted",
                            }
                        )
                if results:
                    messages.append({"role": "user", "content": results})
                raise

            if working_status is not None:
                working_status.stop()

            if results:
                messages.append({"role": "user", "content": results})
            if response.stop_reason != "tool_use":
                return

    except KeyboardInterrupt:
        print("\r", end="", flush=True)
        console.print(
            "[bold yellow]■ Conversation interrupted - tell the model what to do differently[/bold yellow]"
        )
        if thinking_status is not None:
            thinking_status.stop()
        if working_status is not None:
            working_status.stop()
        print()
