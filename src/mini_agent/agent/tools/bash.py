import subprocess
import threading
from collections.abc import Callable

from rich.console import Console
from rich.text import Text

from ...cli.display.theme import LIGHT_HINT_STYLE_RICH
from ...config import WORKDIR
from .base import MAX_OUTPUT, BashInterruptedError, kill_process_tree

console = Console()


def run_bash(
    command: str,
    on_line: Callable[[str], None] | None = None,
    timeout: int | None = None,
) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(token in command for token in dangerous):
        return "Error: Dangerous command blocked"

    proc = subprocess.Popen(
        command,
        shell=True,
        stdin=subprocess.DEVNULL,
        cwd=WORKDIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )

    stdout = proc.stdout
    assert stdout is not None
    output_parts: list[str] = []

    def _read() -> None:
        for line in stdout:
            output_parts.append(line)
            if on_line is not None:
                on_line(line)

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()

    try:
        reader.join(timeout=timeout)
    except KeyboardInterrupt:
        kill_process_tree(proc)
        reader.join(timeout=1)
        output = "".join(output_parts).strip()
        partial = (
            (output[:MAX_OUTPUT] + "\n\nCommand aborted")
            if output
            else "Command aborted"
        )
        raise BashInterruptedError(partial) from None

    if reader.is_alive():
        kill_process_tree(proc)
        reader.join(timeout=1)
        output = "".join(output_parts).strip()
        suffix = f"Command timed out after {timeout} seconds"
        return output[:MAX_OUTPUT] + "\n\n" + suffix if output else suffix

    exit_code = proc.wait()
    output = "".join(output_parts).strip()
    if not output:
        return f"(no output)\n\nCommand exited with code {exit_code}"
    return output[:MAX_OUTPUT]


def bash_handler(command: str, timeout: int | None = None) -> str:
    def on_line(line: str) -> None:
        text = Text.from_ansi(line.rstrip())
        text.stylize(LIGHT_HINT_STYLE_RICH)
        console.print(text)

    return run_bash(command, on_line=on_line, timeout=timeout)
