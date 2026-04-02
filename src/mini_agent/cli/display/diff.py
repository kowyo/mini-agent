import difflib
import shutil

from .theme import GREEN_BG, RED_BG, RESET


def color_full_line(text: str, color: str) -> str:
    width = shutil.get_terminal_size(fallback=(80, 24)).columns
    padding = max(width - len(text), 0)
    return f"{color}{text}{' ' * padding}{RESET}"


def format_edit_diff(old_text: str, new_text: str, start_line: int) -> str:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    formatted_lines: list[str] = []
    old_line_no = start_line
    new_line_no = start_line
    max_line_no = max(
        start_line,
        start_line + len(old_lines) - 1,
        start_line + len(new_lines) - 1,
    )
    line_no_width = len(str(max_line_no))

    def format_line(line_no: int, marker: str, content: str) -> str:
        return f"{line_no:>{line_no_width}} {marker} {content or ' '}"

    def append_deletions(lines: list[str]) -> None:
        nonlocal old_line_no
        for line in lines:
            formatted_lines.append(
                color_full_line(format_line(old_line_no, "-", line), RED_BG)
            )
            old_line_no += 1

    def append_insertions(lines: list[str]) -> None:
        nonlocal new_line_no
        for line in lines:
            formatted_lines.append(
                color_full_line(format_line(new_line_no, "+", line), GREEN_BG)
            )
            new_line_no += 1

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for old_line, _new_line in zip(
                old_lines[i1:i2], new_lines[j1:j2], strict=True
            ):
                formatted_lines.append(format_line(new_line_no, " ", old_line))
                old_line_no += 1
                new_line_no += 1
        elif tag == "delete":
            append_deletions(old_lines[i1:i2])
        elif tag == "insert":
            append_insertions(new_lines[j1:j2])
        elif tag == "replace":
            append_deletions(old_lines[i1:i2])
            append_insertions(new_lines[j1:j2])

    return "\n".join(formatted_lines)
