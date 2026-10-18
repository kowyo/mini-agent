from rich.console import Console
from rich.status import Status

from ..cli.display import display_stream_events, print_tool_result, print_tool_start
from ..cli.models import get_max_output_tokens
from ..cli.token import token_tracker
from ..config import config
from .api import get_backend
from .api.base import TurnRequest
from .tools import TOOL_HANDLERS, BashInterruptedError, ToolError
from .transcript import (
    Message,
    ToolCall,
    ToolResultMessage,
    Transcript,
    content_to_blocks,
)

_console = Console()


def _discard_incomplete_turn(messages: list[Message], turn_start: int) -> None:
    del messages[turn_start:]


def agent_loop(transcript: Transcript, session_id: str | None = None) -> None:
    turn_start = max(len(transcript.messages) - 1, 0)
    model = config.get_model()
    max_tokens = get_max_output_tokens(model)

    working_status: Status | None = None
    thinking_status: Status | None = None

    try:
        while True:
            working_status = None
            thinking_status = _console.status("Thinking")
            thinking_status.start()

            request = TurnRequest(
                transcript=transcript,
                provider=config.get_provider(),
                model=model,
                reasoning_effort=config.get_reasoning_effort(),
                session_id=session_id,
                max_output_tokens=max_tokens,
            )

            try:
                backend = get_backend(request.provider)
                with backend.run_turn(request) as stream:
                    thinking_status.stop()
                    display_stream_events(stream)
                    assistant = stream.get_final_message()

            except Exception as e:
                thinking_status.stop()
                _console.print(f"{type(e).__name__}: {e}", style="bold red")
                _console.print()
                _discard_incomplete_turn(transcript.messages, turn_start)
                return

            transcript.messages.append(assistant)
            token_tracker.update(assistant.usage)

            calls = [
                block for block in assistant.content if isinstance(block, ToolCall)
            ]
            results: list[ToolResultMessage] = []
            try:
                for call in calls:
                    if working_status is None:
                        working_status = _console.status("Working")
                        working_status.start()
                    handler = TOOL_HANDLERS.get(call.name)
                    print_tool_start(call.name, call.arguments)

                    if working_status is not None:
                        working_status.stop()
                        working_status = None

                    interrupted = False
                    try:
                        output = (
                            handler(**call.arguments)
                            if handler
                            else ToolError(f"Unknown tool: {call.name}")
                        )
                    except BashInterruptedError as e:
                        output = e.partial_output
                        interrupted = True

                    is_error = isinstance(output, ToolError)
                    if isinstance(output, ToolError):
                        output = output.content
                    results.append(
                        ToolResultMessage(
                            tool_call_id=call.id,
                            name=call.name,
                            content=content_to_blocks(output),
                            is_error=is_error,
                        )
                    )
                    print_tool_result(call.name, call.arguments, output)
                    if interrupted:
                        raise KeyboardInterrupt
            except KeyboardInterrupt:
                completed_ids = {result.tool_call_id for result in results}
                for remaining in calls:
                    if remaining.id not in completed_ids:
                        results.append(
                            ToolResultMessage(
                                tool_call_id=remaining.id,
                                name=remaining.name,
                                content=content_to_blocks("Command aborted"),
                            )
                        )
                if results:
                    transcript.messages.extend(results)
                raise

            if working_status is not None:
                working_status.stop()

            if results:
                transcript.messages.extend(results)
            if not calls:
                return

    except KeyboardInterrupt:
        print("\r", end="", flush=True)
        _console.print(
            "[bold yellow]■ Conversation interrupted - tell the model what to do differently[/bold yellow]"
        )
        if thinking_status is not None:
            thinking_status.stop()
        if working_status is not None:
            working_status.stop()
        print()
