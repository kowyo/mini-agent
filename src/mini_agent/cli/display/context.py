from pathlib import Path

from rich.console import Console
from rich.text import Text

from ...agent.skills import skill_loader
from ...agent.system_prompt import context_files as loaded_context_files

_console = Console()


def print_context_files() -> None:
    if not loaded_context_files:
        return
    _console.print("\\[Context]")
    cwd = Path.cwd()
    home = Path.home()
    parts = Text()
    for i, path in enumerate(loaded_context_files):
        if i > 0:
            parts.append(", ")
        try:
            parts.append(str(path.relative_to(cwd)))
        except ValueError:
            try:
                parts.append(f"~/{path.relative_to(home)}")
            except ValueError:
                parts.append(str(path))
    _console.print(Text("  ") + parts)
    print()


def print_skills() -> None:
    if not skill_loader.skills:
        return
    _console.print("\\[Skills]")
    parts = Text()
    for i, name in enumerate(skill_loader.skills):
        if i > 0:
            parts.append(", ")
        parts.append(name)
    _console.print(Text("  ") + parts)
    print()
