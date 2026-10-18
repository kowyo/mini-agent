import base64
import io
import math
import os
from typing import Literal

from PIL import Image

_ImageProtocol = Literal["kitty", "iterm2"]

_MAX_WIDTH_CELLS = 60
_CELL_WIDTH_PX = 9
_CELL_HEIGHT_PX = 18
_KITTY_CHUNK_SIZE = 4096


def _detect_image_protocol() -> _ImageProtocol | None:
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    term = os.environ.get("TERM", "").lower()
    if os.environ.get("TMUX") or term.startswith(("tmux", "screen")):
        return None
    if (
        os.environ.get("KITTY_WINDOW_ID")
        or os.environ.get("GHOSTTY_RESOURCES_DIR")
        or os.environ.get("WEZTERM_PANE")
        or term_program in ("kitty", "ghostty", "wezterm")
        or "ghostty" in term
    ):
        return "kitty"
    if os.environ.get("ITERM_SESSION_ID") or term_program == "iterm.app":
        return "iterm2"
    return None


def render_image(data: str, terminal_width: int) -> str | None:
    protocol = _detect_image_protocol()
    if protocol is None:
        return None
    try:
        raw = base64.b64decode(data)
        with Image.open(io.BytesIO(raw)) as image:
            width_px, height_px = image.size
            if protocol == "kitty" and image.format != "PNG":
                png = io.BytesIO()
                image.save(png, "PNG")
                data = base64.b64encode(png.getvalue()).decode()
    except OSError, ValueError, Image.DecompressionBombError:
        return None
    columns, rows = _image_cell_size(
        width_px, height_px, max(1, min(terminal_width - 2, _MAX_WIDTH_CELLS))
    )
    if protocol == "kitty":
        return _encode_kitty(data, columns, rows)
    return (
        f"\x1b]1337;File=inline=1;size={len(raw)};width={columns};height=auto:"
        f"{data}\x07"
    )


def _image_cell_size(
    width_px: int, height_px: int, max_columns: int
) -> tuple[int, int]:
    max_rows = math.ceil(max_columns * _CELL_WIDTH_PX / _CELL_HEIGHT_PX)
    scale = min(
        max_columns * _CELL_WIDTH_PX / width_px,
        max_rows * _CELL_HEIGHT_PX / height_px,
    )
    columns = max(1, min(max_columns, math.ceil(width_px * scale / _CELL_WIDTH_PX)))
    rows = max(1, min(max_rows, math.ceil(height_px * scale / _CELL_HEIGHT_PX)))
    return columns, rows


def _encode_kitty(data: str, columns: int, rows: int) -> str:
    chunks = []
    for offset in range(0, len(data), _KITTY_CHUNK_SIZE):
        more = int(offset + _KITTY_CHUNK_SIZE < len(data))
        keys = (
            f"a=T,f=100,q=2,c={columns},r={rows},m={more}"
            if offset == 0
            else f"m={more}"
        )
        chunks.append(f"\x1b_G{keys};{data[offset : offset + _KITTY_CHUNK_SIZE]}\x1b\\")
    return "".join(chunks)
