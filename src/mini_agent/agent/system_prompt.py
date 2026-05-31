from datetime import date
from pathlib import Path

from ..config import CONFIG_DIR, WORKDIR
from .skills import skill_loader
from .tools import TOOLS

CONTEXT_FILENAMES = ("AGENTS.md",)


def _find_context_in_dir(directory: Path) -> Path | None:
    try:
        entries = {e.name.lower(): e for e in directory.iterdir()}
    except PermissionError, OSError:
        return None
    for name in CONTEXT_FILENAMES:
        entry = entries.get(name.lower())
        if entry is not None and entry.is_file():
            return entry
    return None


def discover_context_files(cwd: Path | None = None) -> list[Path]:
    if cwd is None:
        cwd = Path.cwd()

    seen: set[Path] = set()
    result: list[Path] = []

    def _add(path: Path | None) -> None:
        if path is None:
            return
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)

    _add(_find_context_in_dir(CONFIG_DIR))

    ancestors: list[Path] = []
    current = cwd.resolve()
    while True:
        ancestors.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent

    for directory in reversed(ancestors):
        _add(_find_context_in_dir(directory))

    return result


def _build_context_section(files: list[Path]) -> str:
    if not files:
        return ""

    sections = ["\n<project_instructions>\n"]
    for i, path in enumerate(files, 1):
        try:
            content = path.read_text().strip()
        except PermissionError, OSError:
            continue
        sections.append(
            f'<project_instruction index="{i}" path="{path}">\n{content}\n</project_instruction>\n'
        )
    sections.append("</project_instructions>\n")
    return "".join(sections)


TOOLS_LIST = "\n".join(f"- {tool['name']}: {tool['description']}" for tool in TOOLS)

_SYSTEM_BASE = f"""You are an expert coding assistant. You help users by reading files, executing commands, editing code, and writing new files.

<available_tools>
{TOOLS_LIST}
</available_tools>
"""

SYSTEM = _SYSTEM_BASE
if skill_loader.skills:
    SYSTEM += f"\n{skill_loader.get_descriptions()}\n"

context_files = discover_context_files()
_context_section = _build_context_section(context_files)
if _context_section:
    SYSTEM += _context_section

SYSTEM += (
    f"\nCurrent date: {date.today().isoformat()}\nCurrent working directory: {WORKDIR}"
)
