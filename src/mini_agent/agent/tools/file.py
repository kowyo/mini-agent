import base64
from pathlib import Path
from typing import Any

from .base import resolve_path

MAX_LINES = 2000
MAX_BYTES = 50 * 1024

_EXTENSION_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

_MAGIC_SIGNATURES: list[tuple[str, bytes, int]] = [
    ("image/png", b"\x89PNG\r\n\x1a\n", 0),
    ("image/jpeg", b"\xff\xd8\xff", 0),
    ("image/gif", b"GIF87a", 0),
    ("image/gif", b"GIF89a", 0),
    ("image/webp", b"WEBP", 8),
]


def _detect_image_media_type(file_path: Path) -> str | None:
    media_type = _EXTENSION_MEDIA_TYPES.get(file_path.suffix.lower())
    if media_type:
        return media_type
    try:
        header = file_path.read_bytes()[:16]
    except OSError:
        return None
    for sig_type, signature, offset in _MAGIC_SIGNATURES:
        if header[offset : offset + len(signature)] == signature:
            return sig_type
    return None


def _format_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    return f"{n / (1024 * 1024):.1f}MB"


def run_read(
    path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> str | list[dict[str, Any]]:
    file_path = resolve_path(path)

    media_type = _detect_image_media_type(file_path)
    if media_type:
        try:
            data = base64.standard_b64encode(file_path.read_bytes()).decode()
        except Exception as exc:
            return f"Error: {exc}"
        return [
            {"type": "text", "text": f"Read image file [{media_type}]"},
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": data,
                },
            },
        ]

    try:
        text = file_path.read_text()
    except Exception as exc:
        return f"Error: {exc}"

    all_lines = text.splitlines()
    total = len(all_lines)
    start = max(0, (offset or 1) - 1)

    if start >= total and (total > 0 or start > 0):
        return f"Error: offset {offset} is beyond end of file ({total} lines total)"

    end = min(start + limit, total) if limit is not None else total
    selected = all_lines[start:end]

    output = "\n".join(selected)
    output_bytes = len(output.encode())

    if output_bytes > MAX_BYTES:
        truncated: list[str] = []
        byte_count = 0
        for line in selected:
            line_bytes = len(line.encode()) + (1 if truncated else 0)
            if byte_count + line_bytes > MAX_BYTES:
                break
            truncated.append(line)
            byte_count += line_bytes
        shown_end = start + len(truncated)
        next_offset = shown_end + 1
        output = "\n".join(truncated)
        output += (
            f"\n\n[Showing lines {start + 1}-{shown_end} of {total} "
            f"({_format_size(MAX_BYTES)} limit). Use offset={next_offset} to continue.]"
        )
    elif len(selected) > MAX_LINES:
        selected = selected[:MAX_LINES]
        shown_end = start + MAX_LINES
        next_offset = shown_end + 1
        output = "\n".join(selected)
        output += (
            f"\n\n[Showing lines {start + 1}-{shown_end} of {total}. "
            f"Use offset={next_offset} to continue.]"
        )
    elif end < total:
        remaining = total - end
        next_offset = end + 1
        output += f"\n\n[{remaining} more lines in file. Use offset={next_offset} to continue.]"

    return output


def run_write(path: str, content: str) -> str:
    try:
        file_path = resolve_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as exc:
        return f"Error: {exc}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = resolve_path(path)
        content = file_path.read_text()
        if old_text not in content:
            return f"Error: Text not found in {path}"
        file_path.write_text(content.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as exc:
        return f"Error: {exc}"
