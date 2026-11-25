from prompt_toolkit.buffer import Buffer, CompletionState
from prompt_toolkit.completion import Completion
from prompt_toolkit.document import Document

from mini_agent.cli.display.completion import (
    accept_selected_completion,
    select_first_command_completion,
)


def _buffer_with_completions(text: str, completions: list[Completion]) -> Buffer:
    buffer = Buffer()
    buffer.text = text
    buffer.complete_state = CompletionState(Document(text), completions)
    return buffer


def test_selects_the_first_command_completion() -> None:
    buffer = _buffer_with_completions(
        "/m",
        [
            Completion("/model", start_position=-2, display_meta="Select a model"),
            Completion("/mcp", start_position=-2, display_meta="List MCP servers"),
        ],
    )

    select_first_command_completion(buffer)

    assert buffer.complete_state is not None
    assert buffer.complete_state.complete_index == 0


def test_leaves_file_completions_unselected() -> None:
    buffer = _buffer_with_completions(
        "@src",
        [Completion("src/app.py", start_position=-4)],
    )

    select_first_command_completion(buffer)

    assert buffer.complete_state is not None
    assert buffer.complete_state.complete_index is None


def test_leaves_a_fully_typed_command_unselected() -> None:
    buffer = _buffer_with_completions(
        "/model",
        [Completion("/model", start_position=-6)],
    )

    select_first_command_completion(buffer)

    assert buffer.complete_state is not None
    assert buffer.complete_state.complete_index is None


def test_accept_selected_completion_replaces_the_typed_prefix() -> None:
    buffer = _buffer_with_completions(
        "/mo",
        [Completion("/model", start_position=-3)],
    )
    select_first_command_completion(buffer)

    accept_selected_completion(buffer)

    assert buffer.text == "/model"
    assert buffer.complete_state is None


def test_accept_selected_completion_keeps_an_applied_completion() -> None:
    buffer = _buffer_with_completions(
        "/mo",
        [Completion("/model", start_position=-3)],
    )
    buffer.go_to_completion(0)

    accept_selected_completion(buffer)

    assert buffer.text == "/model"
