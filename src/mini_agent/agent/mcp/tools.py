import atexit
import re
from collections.abc import Callable
from typing import Any

from mcp_types import CallToolResult, ContentBlock, ImageContent, TextContent

from ..tools.base import MAX_OUTPUT, ToolError
from ..tools.handlers import TOOL_HANDLERS
from ..tools.schemas import TOOLS
from .config import load_mcp_servers
from .runtime import McpRuntime, McpServerError

TRUNCATION_MARKER = "\n[output truncated]"

_NAME_SANITIZER = re.compile(r"[^A-Za-z0-9_-]")

runtime = McpRuntime()


def tool_name(server: str, tool: str) -> str:
    return _NAME_SANITIZER.sub("_", f"mcp__{server}__{tool}")


def _unique_name(name: str) -> str:
    if name not in TOOL_HANDLERS:
        return name
    suffix = 2
    while f"{name}_{suffix}" in TOOL_HANDLERS:
        suffix += 1
    return f"{name}_{suffix}"


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + TRUNCATION_MARKER


def _to_block(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextContent):
        return {"type": "text", "text": _truncate(block.text)}
    if isinstance(block, ImageContent):
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": block.mime_type,
                "data": block.data,
            },
        }
    return {"type": "text", "text": _truncate(block.model_dump_json(exclude_none=True))}


def map_result(result: CallToolResult) -> str | list[dict[str, Any]] | ToolError:
    blocks = [_to_block(block) for block in result.content]
    content: str | list[dict[str, Any]]
    if all(block["type"] == "text" for block in blocks):
        content = _truncate("\n".join(block["text"] for block in blocks))
    else:
        content = blocks
    if result.is_error:
        return ToolError(content or "Tool reported an error with no content")
    return content or "(no content)"


def _make_handler(server: str, tool: str) -> Callable[..., object]:
    def handler(**arguments: object) -> str | list[dict[str, Any]] | ToolError:
        try:
            result = runtime.call_tool(server, tool, dict(arguments))
        except McpServerError as exc:
            return ToolError(str(exc))
        return map_result(result)

    return handler


def setup_mcp() -> list[str]:
    servers, errors = load_mcp_servers()
    lines = [f"mcp: {error}" for error in errors]
    connected = False
    for cfg in servers.values():
        try:
            runtime.connect(cfg)
        except McpServerError as exc:
            lines.append(f"mcp: {exc}")
            continue
        connected = True
        try:
            tools = runtime.list_tools(cfg.name)
        except McpServerError as exc:
            lines.append(f"mcp: {exc}")
            continue
        for tool in tools:
            name = _unique_name(tool_name(cfg.name, tool.name))
            TOOLS.append(
                {
                    "name": name,
                    "description": tool.description or tool.title or tool.name,
                    "input_schema": tool.input_schema,
                }
            )
            TOOL_HANDLERS[name] = _make_handler(cfg.name, tool.name)
        lines.append(f"mcp: connected {cfg.name} ({len(tools)} tools)")
    if connected:
        atexit.register(runtime.shutdown)
    return lines
