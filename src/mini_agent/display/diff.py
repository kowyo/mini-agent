import difflib

RED_BG = "\x1b[48;5;224m\x1b[30m"
GREEN_BG = "\x1b[48;5;194m\x1b[30m"
LIGHT_TEXT = "\x1b[37m"
RESET = "\x1b[0m"


def color_full_line(text: str, color: str) -> str:
    return f"{color}{text}\x1b[K{RESET}"


def format_edit_diff(old_text: str, new_text: str, start_line: int) -> str:
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    formatted_lines: list[str] = []
    old_line_no = start_line
    new_line_no = start_line

    def append_deletions(lines: list[str]) -> None:
        nonlocal old_line_no
        for line in lines:
            formatted_lines.append(
                color_full_line(f"{old_line_no} - {line or ' '}", RED_BG)
            )
            old_line_no += 1

    def append_insertions(lines: list[str]) -> None:
        nonlocal new_line_no
        for line in lines:
            formatted_lines.append(
                color_full_line(f"{new_line_no} + {line or ' '}", GREEN_BG)
            )
            new_line_no += 1

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for old_line, _new_line in zip(
                old_lines[i1:i2], new_lines[j1:j2], strict=True
            ):
                formatted_lines.append(f"{new_line_no}  {old_line}")
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
