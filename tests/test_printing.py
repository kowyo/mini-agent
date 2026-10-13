import pytest
from anthropic.types import TextBlock, ToolUseBlock

from mini_agent.cli.display import printing


@pytest.fixture(autouse=True)
def collapsed_tool_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(printing, "_full_tool_output", False)


def test_long_tool_output_is_truncated_with_expand_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = "x" * 300

    printing.print_tool_result("mcp__server__tool", {}, output)

    printed = capsys.readouterr().out
    assert "x" * 200 in printed
    assert "x" * 201 not in printed
    assert "ctrl+o to expand" in printed


def test_toggled_tool_output_is_printed_in_full(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = "x" * 300

    assert printing.toggle_full_tool_output() is True
    printing.print_tool_result("mcp__server__tool", {}, output)

    printed = capsys.readouterr().out
    assert output in printed
    assert "ctrl+o to expand" not in printed


def test_session_history_redraws_live_sdk_blocks(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(printing, "clear_terminal", lambda: None)
    history = [
        {"role": "user", "content": "list pages"},
        {
            "role": "assistant",
            "content": [
                TextBlock(type="text", text="Let me list pages."),
                ToolUseBlock(
                    type="tool_use",
                    id="t1",
                    name="mcp__chrome-devtools__list_pages",
                    input={},
                ),
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "## Pages"}
            ],
        },
    ]

    printing.print_session_history(history)

    printed = capsys.readouterr().out
    assert "Let me list pages." in printed
    assert "> mcp__chrome-devtools__list_pages - {}" in printed
    assert "## Pages" in printed
