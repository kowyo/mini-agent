from .base import resolve_path

MAX_LINES = 2000
MAX_BYTES = 50 * 1024


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
) -> str:
    try:
        text = resolve_path(path).read_text()
    except Exception as exc:
        return f"Error: {exc}"

    all_lines = text.splitlines()
    total = len(all_lines)
    start = max(0, (offset or 1) - 1)

    if start >= total:
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
