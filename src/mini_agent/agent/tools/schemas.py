from anthropic.types import ToolParam

from .file import MAX_BYTES, MAX_LINES

TOOLS: list[ToolParam] = [
    {
        "name": "bash",
        "description": "Execute bash commands.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Maximum seconds to wait. If omitted, runs until completion",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": (
            f"Read the contents of a file. Supports text files and images "
            f"(jpg, jpeg, png, gif, webp). Images are sent as attachments. "
            f"For text files, output is truncated to {MAX_LINES} lines or "
            f"{MAX_BYTES // 1024}KB (whichever is hit first). Use offset/limit for "
            f"large files. When you need the full file, continue with offset until complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (relative or absolute)",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Line number to start reading from (1-indexed)",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Maximum number of lines to read",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace exact text in a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "activate_skill",
        "description": "Load specialized knowledge by name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill name to load"}
            },
            "required": ["name"],
        },
    },
]
