import os
import signal
import subprocess
import sys
from pathlib import Path

from ...config import WORKDIR

MAX_OUTPUT = 50000


class BashInterruptedError(Exception):
    def __init__(self, partial_output: str) -> None:
        self.partial_output = partial_output


def kill_process_tree(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    return path.resolve() if path.is_absolute() else (WORKDIR / path_str).resolve()
