import asyncio
import contextlib
import os
import threading
from collections.abc import AsyncIterator, Coroutine
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import Client, MCPError, StdioServerParameters
from mcp.client.stdio import TransportStreams, stdio_client
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
from mcp_types import CONNECTION_CLOSED, CallToolResult, Tool

from .auth import AUTHORIZATION_TIMEOUT, AuthorizationRequiredError, build_auth
from .config import HttpServerConfig, ServerConfig, StdioServerConfig

CONNECT_TIMEOUT = 10.0
SHUTDOWN_TIMEOUT = 15.0


class McpServerError(Exception):
    pass


class McpAuthRequiredError(McpServerError):
    pass


def _needs_oauth(cfg: ServerConfig) -> bool:
    return isinstance(cfg, HttpServerConfig) and not any(
        key.lower() == "authorization" for key in cfg.headers
    )


def _connect_timeout(cfg: ServerConfig, interactive: bool) -> float:
    if interactive and _needs_oauth(cfg):
        return AUTHORIZATION_TIMEOUT
    return CONNECT_TIMEOUT


def _leaf_exception(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _contains(exc: BaseException | None, exc_type: type[BaseException]) -> bool:
    while exc is not None:
        if isinstance(exc, exc_type):
            return True
        if isinstance(exc, BaseExceptionGroup):
            return any(_contains(sub, exc_type) for sub in exc.exceptions)
        exc = exc.__cause__ or exc.__context__
    return False


@dataclass
class _ServerHandle:
    client: Client
    stop: asyncio.Event
    task: asyncio.Task
    timeout: float


@asynccontextmanager
async def _http_transport(
    cfg: HttpServerConfig, interactive: bool
) -> AsyncIterator[TransportStreams]:
    auth = build_auth(cfg, interactive) if _needs_oauth(cfg) else None
    http = create_mcp_http_client(headers=cfg.headers or None, auth=auth)
    async with http, streamable_http_client(cfg.url, http_client=http) as streams:
        yield streams


@asynccontextmanager
async def _stdio_transport(cfg: StdioServerConfig) -> AsyncIterator[TransportStreams]:
    params = StdioServerParameters(
        command=cfg.command, args=cfg.args, env=cfg.env or None
    )
    with Path(os.devnull).open("w") as errlog:
        async with stdio_client(params, errlog=errlog) as streams:
            yield streams


def _make_transport(
    cfg: ServerConfig, interactive: bool
) -> AbstractAsyncContextManager[TransportStreams]:
    if isinstance(cfg, StdioServerConfig):
        return _stdio_transport(cfg)
    return _http_transport(cfg, interactive)


class McpRuntime:
    """Runs MCP I/O on one event-loop thread, one holder task per server
    (the SDK requires a client to enter and exit in the same task)."""

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

    async def _start(self, cfg: ServerConfig, interactive: bool) -> _ServerHandle:
        loop = asyncio.get_running_loop()
        ready: asyncio.Future[Client] = loop.create_future()
        stop = asyncio.Event()

        async def _serve() -> None:
            try:
                async with Client(_make_transport(cfg, interactive)) as client:
                    if not ready.done():
                        ready.set_result(client)
                    await stop.wait()
            except Exception as exc:
                if not ready.done():
                    ready.set_exception(exc)

        task = loop.create_task(_serve())
        connect_timeout = _connect_timeout(cfg, interactive)
        try:
            client = await asyncio.wait_for(asyncio.shield(ready), connect_timeout)
        except TimeoutError:
            stop.set()
            task.cancel()
            raise McpServerError(
                f"{cfg.name}: did not start within {connect_timeout:g}s"
            ) from None
        except McpServerError:
            raise
        except Exception as exc:
            if _contains(exc, AuthorizationRequiredError):
                raise McpAuthRequiredError(
                    f"{cfg.name}: authorization required"
                ) from exc
            raise McpServerError(f"{cfg.name}: {_leaf_exception(exc)}") from exc
        return _ServerHandle(client=client, stop=stop, task=task, timeout=cfg.timeout)

    def connect(self, cfg: ServerConfig, interactive: bool = True) -> None:
        if cfg.name in self._servers:
            raise McpServerError(f"{cfg.name}: already connected")
        self._servers[cfg.name] = self._run(
            self._start(cfg, interactive), _connect_timeout(cfg, interactive) + 5
        )

    def connect_all(
        self, cfgs: list[ServerConfig], interactive: bool = False
    ) -> dict[str, McpServerError | None]:
        cfgs = [cfg for cfg in cfgs if cfg.name not in self._servers]
        if not cfgs:
            return {}

        async def _all() -> list[_ServerHandle | BaseException]:
            return await asyncio.gather(
                *(self._start(cfg, interactive) for cfg in cfgs),
                return_exceptions=True,
            )

        statuses: dict[str, McpServerError | None] = {}
        outer_timeout = max(_connect_timeout(cfg, interactive) for cfg in cfgs) + 5
        results = self._run(_all(), outer_timeout)
        for cfg, result in zip(cfgs, results, strict=True):
            if isinstance(result, _ServerHandle):
                self._servers[cfg.name] = result
                statuses[cfg.name] = None
            elif isinstance(result, McpServerError):
                statuses[cfg.name] = result
            else:
                statuses[cfg.name] = McpServerError(f"{cfg.name}: {result}")
        return statuses

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
