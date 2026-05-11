from typing import Any

from ..skills import skill_loader
from .bash import bash_handler
from .file import run_edit, run_read, run_write

TOOL_HANDLERS: dict[str, Any] = {
    "bash": bash_handler,
    "read_file": lambda **kw: run_read(kw["path"], kw.get("limit")),
    "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
    "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    "activate_skill": lambda **kw: skill_loader.get_content(kw["name"]),
}
