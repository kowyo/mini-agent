from rich.console import Console

from ..agent.mcp import (
    ServerStatus,
    authorize_server,
    pending_auth_count,
    server_statuses,
)
from .display.picker import select_from_list
from .display.theme import LIGHT_HINT_STYLE_RICH

console = Console()


def _format_mcp_server(status: ServerStatus) -> str:
    if status.needs_auth:
        return f"{status.name} — authorization required"
    if status.error is not None:
        return f"{status.name} — failed: {status.error}"
    return f"{status.name} — {len(status.tools)} tools"


def prompt_mcp() -> None:
    if not server_statuses:
        console.print("mcp: no servers configured", style=LIGHT_HINT_STYLE_RICH)
        print()
        return
    chosen = select_from_list(
        list(server_statuses),
        "",
        _format_mcp_server,
        clear_after=True,
        enable_search=False,
        mark_initial=False,
    )
    if chosen is None:
        return
    if chosen.error is None:
        console.print(
            f"mcp: {chosen.name}: {', '.join(chosen.tools) or 'no tools'}",
            style=LIGHT_HINT_STYLE_RICH,
        )
    else:
        console.print(authorize_server(chosen.name), style=LIGHT_HINT_STYLE_RICH)
    print()


def print_mcp_hint() -> None:
    pending = pending_auth_count()
    if pending:
        label = "server needs" if pending == 1 else "servers need"
        print()
        console.print(
            f"{pending} MCP {label} authorization — run /mcp to connect",
            style=LIGHT_HINT_STYLE_RICH,
        )
        print()
