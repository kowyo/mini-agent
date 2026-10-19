import os
import subprocess


def clear_terminal() -> None:
    subprocess.run(
        ["cls" if os.name == "nt" else "clear"],
        check=False,
        shell=os.name == "nt",
    )


def clear_prompt_line() -> None:
    print("\r\033[2K\033[1A\033[2K\r", end="", flush=True)
