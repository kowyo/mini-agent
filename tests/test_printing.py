import base64
import io
from collections.abc import Callable
from pathlib import Path

import pytest
from anthropic.types import ToolUseBlock
from PIL import Image

from mini_agent.agent.tools.file import run_read
from mini_agent.cli.display import printing


def test_ctrl_o_toggles_collapsed_tool_output(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(printing, "_full_tool_output", False)
    output = "\n".join(f"line {i}" for i in range(1, 16))

    printing.print_tool_result("mcp__server__tool", {}, output)
    collapsed = capsys.readouterr().out
    printing.toggle_full_tool_output()
    printing.print_tool_result("mcp__server__tool", {}, output)
    expanded = capsys.readouterr().out

    assert "line 11" not in collapsed
    assert "… (5 more lines, ctrl+o to expand)" in collapsed
    assert "line 15" in expanded
    assert "ctrl+o to expand" not in expanded


def test_collapsed_tool_output_bounds_long_lines_and_images(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(printing, "_full_tool_output", False)
    monkeypatch.setattr(printing.console, "width", 80)
    image = {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "A" * 5000},
    }
    output = [image, {"type": "text", "text": "x" * 2000}]

    printing.print_tool_result("mcp__server__tool", {}, output)

    printed = capsys.readouterr().out
    assert "A" * 100 not in printed
    assert "[image/png]" in printed
    assert len(printed) < 2000
    assert "more lines, ctrl+o to expand" in printed


@pytest.mark.parametrize("full_output", [False, True])
def test_tool_result_images_render_inline(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    terminal_env: Callable[..., None],
    full_output: bool,
) -> None:
    terminal_env(TERM_PROGRAM="kitty")
    monkeypatch.setattr(printing, "_full_tool_output", full_output)
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, "PNG")
    image = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(buffer.getvalue()).decode(),
        },
    }
    output = [{"type": "text", "text": "Took a screenshot"}, image]

    printing.print_tool_result("mcp__chrome__take_screenshot", {}, output)

    printed = capsys.readouterr().out
    assert printed.startswith("Took a screenshot\n\x1b_Ga=T,f=100")
    assert "[image/png]" not in printed


def test_read_file_shows_label_and_image(
    capsys: pytest.CaptureFixture[str],
    terminal_env: Callable[..., None],
    tmp_path: Path,
) -> None:
    terminal_env(TERM_PROGRAM="kitty")
    path = tmp_path / "shot.png"
    Image.new("RGB", (8, 8)).save(path)

    printing.print_tool_result("read_file", {"path": str(path)}, run_read(str(path)))

    printed = capsys.readouterr().out
    assert printed.startswith("Read image file [image/png]\n\x1b_Ga=T,f=100")


def test_read_file_image_falls_back_to_placeholder(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    path = tmp_path / "shot.png"
    Image.new("RGB", (8, 8)).save(path)

    printing.print_tool_result("read_file", {"path": str(path)}, run_read(str(path)))

    printed = capsys.readouterr().out
    assert "[image/png]" in printed
    assert "\x1b_G" not in printed


def test_session_history_redraws_live_tool_calls(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(printing, "clear_terminal", lambda: None)
    tool_use = ToolUseBlock(type="tool_use", id="t1", name="mcp__x__list", input={})

    printing.print_session_history([{"role": "assistant", "content": [tool_use]}])

    assert "> mcp__x__list - {}" in capsys.readouterr().out
