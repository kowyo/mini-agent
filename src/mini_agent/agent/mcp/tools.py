import atexit
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mcp_types import CallToolResult, ContentBlock, ImageContent, TextContent

from ..tools.base import MAX_OUTPUT, ToolError
from ..tools.handlers import TOOL_HANDLERS
from ..tools.schemas import TOOLS
from .config import ServerConfig, load_mcp_servers
from .runtime import McpAuthRequiredError, McpRuntime, McpServerError

TRUNCATION_MARKER = "\n[output truncated]"

_NAME_SANITIZER = re.compile(r"[^A-Za-z0-9_-]")

runtime = McpRuntime()


@dataclass
class ServerStatus:
    name: str
    tools: list[str] = field(default_factory=list)
    error: str | None = None
    needs_auth: bool = False


server_statuses: list[ServerStatus] = []
_configs: dict[str, ServerConfig] = {}
_pending_auth: dict[str, ServerConfig] = {}
_shutdown_registered = False


def pending_auth_count() -> int:
    return len(_pending_auth)


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


def shutdown_mcp() -> None:
    runtime.shutdown()


def _ensure_shutdown_hook() -> None:
    global _shutdown_registered
    if not _shutdown_registered:
        atexit.register(runtime.shutdown)
        _shutdown_registered = True


def _set_status(status: ServerStatus) -> None:
    server_statuses[:] = [s for s in server_statuses if s.name != status.name]
    server_statuses.append(status)


def _register_tools(cfg: ServerConfig) -> ServerStatus:
    try:
        tools = runtime.list_tools(cfg.name)
    except McpServerError as exc:
        return ServerStatus(name=cfg.name, error=str(exc))
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
    return ServerStatus(name=cfg.name, tools=[tool.name for tool in tools])


def setup_mcp() -> list[str]:
    servers, errors = load_mcp_servers()
    lines = [f"mcp: {error}" for error in errors]
    server_statuses.clear()
    _pending_auth.clear()
    _configs.clear()
    _configs.update(servers)
    if not servers:
        return lines
    statuses = runtime.connect_all(list(servers.values()), interactive=False)
    for cfg in servers.values():
        status = statuses.get(cfg.name)
        if isinstance(status, McpAuthRequiredError):
            _pending_auth[cfg.name] = cfg
            _set_status(ServerStatus(name=cfg.name, error=str(status), needs_auth=True))
            continue
        if status is not None:
            lines.append(f"mcp: {status}")
            _set_status(ServerStatus(name=cfg.name, error=str(status)))
            continue
        _ensure_shutdown_hook()
        registered = _register_tools(cfg)
        if registered.error is not None:
            lines.append(f"mcp: {registered.error}")
        _set_status(registered)
    return lines


def authorize_server(name: str) -> str:
    cfg = _configs.get(name)
    if cfg is None:
        return f"mcp: unknown server {name!r}"
    current = next((s for s in server_statuses if s.name == name), None)
    if current is not None and current.error is None:
        return f"mcp: {name}: already connected ({len(current.tools)} tools)"
    try:
        runtime.connect(cfg, interactive=True)
    except McpServerError as exc:
        _set_status(
            ServerStatus(
                name=name,
                error=str(exc),
                needs_auth=isinstance(exc, McpAuthRequiredError),
            )
        )
        return f"mcp: {exc}"
    _pending_auth.pop(name, None)
    _ensure_shutdown_hook()
    registered = _register_tools(cfg)
    _set_status(registered)
    if registered.error is not None:
        return f"mcp: {registered.error}"
    return f"mcp: connected {name} ({len(registered.tools)} tools)"
