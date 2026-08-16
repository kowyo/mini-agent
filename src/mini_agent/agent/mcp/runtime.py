import asyncio
import contextlib
import threading
from collections.abc import Coroutine
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from mcp import Client, MCPError, StdioServerParameters
from mcp.client.stdio import TransportStreams, stdio_client
from mcp_types import CONNECTION_CLOSED, CallToolResult, Tool

from .config import ServerConfig, StdioServerConfig

CONNECT_TIMEOUT = 10.0
SHUTDOWN_TIMEOUT = 15.0


class McpServerError(Exception):
    pass


@dataclass
class _ServerHandle:
    client: Client
    stop: asyncio.Event
    task: asyncio.Task
    timeout: float


def _make_transport(cfg: ServerConfig) -> AbstractAsyncContextManager[TransportStreams]:
    if isinstance(cfg, StdioServerConfig):
        params = StdioServerParameters(
            command=cfg.command, args=cfg.args, env=cfg.env or None
        )
        return stdio_client(params)
    raise McpServerError(f"{cfg.name}: unsupported server config")


class McpRuntime:
    """Runs all MCP I/O on one background event-loop thread.

    The async SDK binds each client to the task that entered it, so every
    server gets a dedicated task that holds the connection open until stop
    is set; synchronous callers submit coroutines to the loop and block on
    the result.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._servers: dict[str, _ServerHandle] = {}

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            threading.Thread(
                target=self._loop.run_forever, daemon=True, name="mcp-runtime"
            ).start()
        return self._loop

    def _run[T](self, coro: Coroutine[Any, Any, T], timeout: float) -> T:
        future = asyncio.run_coroutine_threadsafe(coro, self._ensure_loop())
        try:
            return future.result(timeout)
        except TimeoutError:
            future.cancel()
            raise

    def connect(self, cfg: ServerConfig) -> None:
        if cfg.name in self._servers:
            raise McpServerError(f"{cfg.name}: already connected")

        async def _start() -> _ServerHandle:
            loop = asyncio.get_running_loop()
            ready: asyncio.Future[Client] = loop.create_future()
            stop = asyncio.Event()

            async def _serve() -> None:
                try:
                    async with Client(_make_transport(cfg)) as client:
                        if not ready.done():
                            ready.set_result(client)
                        await stop.wait()
                except Exception as exc:
                    if not ready.done():
                        ready.set_exception(exc)

            task = loop.create_task(_serve())
            try:
                client = await asyncio.wait_for(asyncio.shield(ready), CONNECT_TIMEOUT)
            except TimeoutError:
                stop.set()
                task.cancel()
                raise McpServerError(
                    f"{cfg.name}: did not start within {CONNECT_TIMEOUT:g}s"
                ) from None
            except McpServerError:
                raise
            except Exception as exc:
                raise McpServerError(f"{cfg.name}: {exc}") from exc
            return _ServerHandle(
                client=client, stop=stop, task=task, timeout=cfg.timeout
            )

        self._servers[cfg.name] = self._run(_start(), CONNECT_TIMEOUT + 5)

    def _handle(self, server: str) -> _ServerHandle:
        handle = self._servers.get(server)
        if handle is None:
            raise McpServerError(f"MCP server {server!r} is not connected")
        return handle

    def list_tools(self, server: str) -> list[Tool]:
        handle = self._handle(server)

        async def _list() -> list[Tool]:
            tools: list[Tool] = []
            cursor: str | None = None
            while True:
                page = await handle.client.list_tools(cursor=cursor)
                tools.extend(page.tools)
                if page.next_cursor is None:
                    return tools
                cursor = page.next_cursor

        try:
            return self._run(_list(), handle.timeout)
        except TimeoutError:
            raise McpServerError(
                f"{server}: tools/list timed out after {handle.timeout:g}s"
            ) from None
        except Exception as exc:
            raise McpServerError(f"{server}: {exc}") from exc

    def call_tool(
        self, server: str, tool: str, arguments: dict[str, Any]
    ) -> CallToolResult:
        handle = self._handle(server)

        async def _call() -> CallToolResult:
            return await handle.client.call_tool(tool, arguments)

        try:
            return self._run(_call(), handle.timeout)
        except TimeoutError:
            raise McpServerError(
                f"{server}.{tool}: timed out after {handle.timeout:g}s"
            ) from None
        except MCPError as exc:
            if exc.code != CONNECTION_CLOSED:
                raise McpServerError(f"{server}.{tool}: {exc.message}") from exc
            self._disconnect(server)
            raise McpServerError(
                f"{server}.{tool}: connection lost; server disabled"
            ) from exc
        except Exception as exc:
            self._disconnect(server)
            raise McpServerError(
                f"{server}.{tool}: connection lost ({exc}); server disabled"
            ) from exc

    def _disconnect(self, server: str) -> None:
        handle = self._servers.pop(server, None)
        if handle is None or self._loop is None:
            return
        self._loop.call_soon_threadsafe(handle.stop.set)

    def shutdown(self) -> None:
        loop = self._loop
        if loop is None:
            return
        handles = list(self._servers.values())
        self._servers.clear()
        self._loop = None

        async def _stop_all() -> None:
            for handle in handles:
                handle.stop.set()
            await asyncio.gather(
                *(handle.task for handle in handles), return_exceptions=True
            )

        future = asyncio.run_coroutine_threadsafe(_stop_all(), loop)
        with contextlib.suppress(Exception):
            future.result(SHUTDOWN_TIMEOUT)
        loop.call_soon_threadsafe(loop.stop)
