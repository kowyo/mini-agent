"""Build the system prompt, including project-level AGENTS.md discovery."""

from datetime import date
from pathlib import Path

from .agent.skills import skill_loader
from .agent.tools import TOOLS
from .config import WORKDIR

# ---------------------------------------------------------------------------
# Context file discovery
# ---------------------------------------------------------------------------

CONTEXT_FILENAMES = ("AGENTS.md",)
CONFIG_DIR = Path.home() / ".mini-agent"


def _find_context_in_dir(directory: Path) -> Path | None:
    """Check if any context file exists in *directory* (case-insensitive)."""
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
    """Return an ordered list of context file paths to load.

    Order: global first, then ancestors from root → cwd (most specific last).
    Duplicate paths are removed.
    """
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

    # 1. Global config
    _add(_find_context_in_dir(CONFIG_DIR))

    # 2. Walk from cwd up to root, collect ancestors
    ancestors: list[Path] = []
    current = cwd.resolve()
    while True:
        ancestors.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent

    # ancestors is [cwd, parent, ..., root]; reverse so root comes first
    for directory in reversed(ancestors):
        _add(_find_context_in_dir(directory))

    return result


def _build_context_section(files: list[Path]) -> str:
    """Build the ``# Project Context`` section for the system prompt."""
    if not files:
        return ""

    sections = [
        "\n# Project Context\n\nProject-specific instructions and guidelines:\n"
    ]
    for path in files:
        try:
            content = path.read_text().strip()
        except PermissionError, OSError:
            continue
        sections.append(f"\n## {path}\n\n{content}\n")
    return "".join(sections)


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------

TOOLS_LIST = "\n".join(f"- {tool['name']}: {tool['description']}" for tool in TOOLS)

_SYSTEM_BASE = f"""You are an expert coding assistant. You help users by reading files, executing commands, editing code, and writing new files.

Available tools:
{TOOLS_LIST}
"""

SYSTEM = _SYSTEM_BASE
if skill_loader.skills:
    SYSTEM += f"\nAvailable skills:\n{skill_loader.get_descriptions()}\n"

context_files = discover_context_files()
_context_section = _build_context_section(context_files)
if _context_section:
    SYSTEM += _context_section

SYSTEM += (
    f"\nCurrent date: {date.today().isoformat()}\nCurrent working directory: {WORKDIR}"
)
