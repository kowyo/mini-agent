import base64
import io
import random
import re
from collections.abc import Callable

import pytest
from PIL import Image

from mini_agent.cli.display.terminal_image import detect_image_protocol, render_image

KITTY_COMMAND = re.compile(r"\x1b_G([^;]*);([^\x1b]*)\x1b\\")


def encode(width: int, height: int, image_format: str = "PNG") -> str:
    noise = random.Random(0).randbytes(width * height * 3)
    image = Image.frombytes("RGB", (width, height), noise)
    buffer = io.BytesIO()
    image.save(buffer, image_format)
    return base64.b64encode(buffer.getvalue()).decode()


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"KITTY_WINDOW_ID": "1"}, "kitty"),
        ({"TERM_PROGRAM": "ghostty"}, "kitty"),
        ({"TERM": "xterm-ghostty"}, "kitty"),
        ({"WEZTERM_PANE": "0"}, "kitty"),
        ({"ITERM_SESSION_ID": "w0t0p0"}, "iterm2"),
        ({"TERM_PROGRAM": "iTerm.app"}, "iterm2"),
        ({"TERM_PROGRAM": "ghostty", "TMUX": "/tmp/tmux-501/default"}, None),
        ({"KITTY_WINDOW_ID": "1", "TERM": "screen-256color"}, None),
        ({"TERM_PROGRAM": "Apple_Terminal"}, None),
    ],
)
def test_detects_image_protocol_from_environment(
    terminal_env: Callable[..., None], env: dict[str, str], expected: str | None
) -> None:
    terminal_env(**env)

    assert detect_image_protocol() == expected


def test_kitty_sends_png_in_chunks_sized_to_60_cells(
    terminal_env: Callable[..., None],
) -> None:
    terminal_env(TERM_PROGRAM="kitty")
    data = encode(1200, 600)

    commands = KITTY_COMMAND.findall(render_image(data, 200) or "")

    assert commands[0][0] == "a=T,f=100,q=2,c=60,r=15,m=1"
    assert [keys for keys, _ in commands[1:-1]] == ["m=1"] * (len(commands) - 2)
    assert commands[-1][0] == "m=0"
    assert "".join(payload for _, payload in commands) == data


def test_tall_image_fits_height_and_narrow_terminal(
    terminal_env: Callable[..., None],
) -> None:
    terminal_env(TERM_PROGRAM="kitty")

    sequence = render_image(encode(100, 1000), 30) or ""

    assert sequence.startswith("\x1b_Ga=T,f=100,q=2,c=3,r=14,")


def test_kitty_converts_jpeg_to_png(terminal_env: Callable[..., None]) -> None:
    terminal_env(TERM_PROGRAM="ghostty")

    commands = KITTY_COMMAND.findall(render_image(encode(64, 32, "JPEG"), 200) or "")

    png = base64.b64decode("".join(payload for _, payload in commands))
    with Image.open(io.BytesIO(png)) as image:
        assert (image.format, image.size) == ("PNG", (64, 32))


def test_iterm2_sends_original_format(terminal_env: Callable[..., None]) -> None:
    terminal_env(ITERM_SESSION_ID="w0t0p0")
    data = encode(64, 32, "WEBP")

    sequence = render_image(data, 200)

    size = len(base64.b64decode(data))
    assert sequence == (
        f"\x1b]1337;File=inline=1;size={size};width=60;height=auto:{data}\x07"
    )


def test_undecodable_image_is_not_rendered(terminal_env: Callable[..., None]) -> None:
    terminal_env(TERM_PROGRAM="kitty")

    assert render_image("A" * 5000, 200) is None


def test_unsupported_terminal_renders_nothing() -> None:
    assert render_image(encode(64, 32), 200) is None
