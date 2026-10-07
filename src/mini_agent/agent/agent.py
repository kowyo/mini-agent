from rich.console import Console
from rich.status import Status

from ..cli.display import display_stream_events, print_tool_result, print_tool_start
from ..cli.models import get_max_output_tokens
from ..cli.token import token_tracker
from ..config import config
from .providers import get_provider
from .providers.types import Block, Message, ToolResultBlock
from .system_prompt import SYSTEM
from .tools import TOOL_HANDLERS, TOOLS, BashInterruptedError, ToolError

console = Console()


def _discard_incomplete_turn(messages: list[Message], turn_start: int) -> None:
    del messages[turn_start:]


def agent_loop(messages: list[Message]) -> None:
    turn_start = max(len(messages) - 1, 0)
    provider = get_provider()
    model = config.get_model()
    max_tokens = get_max_output_tokens(model) or 32768
    effort = config.get_reasoning_effort()

    working_status: Status | None = None
    thinking_status: Status | None = None

    try:
        while True:
            working_status = None
            thinking_status = console.status("Thinking")
            thinking_status.start()

            try:
                with provider.stream(
                    model=model,
                    system=SYSTEM,
                    messages=messages,
                    tools=TOOLS,
                    effort=effort,
                    cache_control=config.get_cache_control(),
                    max_tokens=max_tokens,
                ) as stream:
                    thinking_status.stop()
                    display_stream_events(stream)
                    turn = stream.get_final_turn()

            except Exception as e:
                thinking_status.stop()
                console.print(f"{type(e).__name__}: {e}", style="bold red")
                console.print()
                _discard_incomplete_turn(messages, turn_start)
                return

            messages.append({"role": "assistant", "content": turn.content})
            token_tracker.update(turn.usage)

            results: list[Block] = []
            completed_ids: set[str] = set()
            try:
                for block in turn.content:
                    if block["type"] != "tool_use":
                        continue
                    if working_status is None:
                        working_status = console.status("Working")
                        working_status.start()
                    handler = TOOL_HANDLERS.get(block["name"])
                    print_tool_start(block["name"], block["input"])

                    if working_status is not None:
                        working_status.stop()
                        working_status = None

                    interrupted = False
                    try:
                        output = (
                            handler(**block["input"])
                            if handler
                            else ToolError(f"Unknown tool: {block['name']}")
                        )
                    except BashInterruptedError as e:
                        output = e.partial_output
                        interrupted = True

                    is_error = isinstance(output, ToolError)
                    if isinstance(output, ToolError):
                        output = output.content
                    result: ToolResultBlock = {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": output,
                    }
                    if is_error:
                        result["is_error"] = True
                    results.append(result)
                    completed_ids.add(block["id"])
                    print_tool_result(block["name"], block["input"], output)
                    if interrupted:
                        raise KeyboardInterrupt
            except KeyboardInterrupt:
                for remaining in turn.content:
                    if (
                        remaining["type"] == "tool_use"
                        and remaining["id"] not in completed_ids
                    ):
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": remaining["id"],
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
            if turn.stop_reason != "tool_use":
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
