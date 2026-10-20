import threading
from concurrent.futures import Future

from rich.console import Console

from .display.picker import select_from_list
from .display.theme import LIGHT_HINT_STYLE_RICH
lazy from ..agent.mcp import (
    ServerStatus,
    authorize_server,
    pending_auth_count,
    server_statuses,
    setup_mcp,
)

_console = Console()


class McpSetup:
    def __init__(self) -> None:
        self._lines: Future[list[str]] = Future()
        self._reported = False
        threading.Thread(target=self._connect, name="mcp-setup", daemon=True).start()

    def _connect(self) -> None:
        try:
            self._lines.set_result(setup_mcp())
        except BaseException as exc:
            self._lines.set_exception(exc)

    def wait(self) -> None:
        if self._reported:
            return
        self._reported = True
        print_mcp_lines(self._lines.result())
        print_mcp_hint()


def print_mcp_lines(lines: list[str]) -> None:
    if not lines:
        return
    for line in lines:
        _console.print(line, style=LIGHT_HINT_STYLE_RICH)
    print()


def _format_mcp_server(status: ServerStatus) -> str:
    if status.needs_auth:
        return f"{status.name} — authorization required"
    if status.error is not None:
        return f"{status.name} — failed: {status.error}"
    return f"{status.name} — {len(status.tools)} tools"


def prompt_mcp() -> None:
    if not server_statuses:
        _console.print("mcp: no servers configured", style=LIGHT_HINT_STYLE_RICH)
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
        _console.print(
            f"mcp: {chosen.name}: {', '.join(chosen.tools) or 'no tools'}",
            style=LIGHT_HINT_STYLE_RICH,
        )
    else:
        _console.print(authorize_server(chosen.name), style=LIGHT_HINT_STYLE_RICH)
    print()


def print_mcp_hint() -> None:
    pending = pending_auth_count()
    if pending:
        label = "server needs" if pending == 1 else "servers need"
        print()
        _console.print(
            f"{pending} MCP {label} authorization — run /mcp to connect",
            style=LIGHT_HINT_STYLE_RICH,
        )
        print()
