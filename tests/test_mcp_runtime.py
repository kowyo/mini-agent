import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from mcp_types import TextContent

from mini_agent.agent.mcp.config import HttpServerConfig, StdioServerConfig
from mini_agent.agent.mcp.runtime import McpRuntime, McpServerError

STUB_SERVER = Path(__file__).parent / "mcp_stub_server.py"


def stub_config(name: str = "stub", timeout: float = 10.0) -> StdioServerConfig:
    return StdioServerConfig(
        name=name,
        command=sys.executable,
        args=[str(STUB_SERVER)],
        timeout=timeout,
    )


@pytest.fixture
def runtime() -> Iterator[McpRuntime]:
    rt = McpRuntime()
    yield rt
    rt.shutdown()


def test_connect_list_call(runtime: McpRuntime) -> None:
    runtime.connect(stub_config())
    tools = runtime.list_tools("stub")
    names = {tool.name for tool in tools}
    assert {"echo", "fail"} <= names
    echo = next(tool for tool in tools if tool.name == "echo")
    assert echo.input_schema["properties"]["text"]["type"] == "string"

    result = runtime.call_tool("stub", "echo", {"text": "hello"})
    assert result.is_error is False
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == "hello"


def test_tool_failure_sets_is_error(runtime: McpRuntime) -> None:
    runtime.connect(stub_config())
    result = runtime.call_tool("stub", "fail", {})
    assert result.is_error is True
    assert "intentional failure" in result.content[0].text


def test_connect_failure_raises(runtime: McpRuntime) -> None:
    bad = StdioServerConfig(name="bad", command="mini-agent-no-such-command")
    with pytest.raises(McpServerError, match="bad"):
        runtime.connect(bad)
    with pytest.raises(McpServerError, match="not connected"):
        runtime.call_tool("bad", "echo", {})


def test_call_timeout(runtime: McpRuntime) -> None:
    runtime.connect(stub_config(timeout=1.0))
    with pytest.raises(McpServerError, match="timed out"):
        runtime.call_tool("stub", "sleep", {"seconds": 10})


def test_server_death_disables_server(runtime: McpRuntime) -> None:
    runtime.connect(stub_config())
    with pytest.raises(McpServerError):
        runtime.call_tool("stub", "die", {})
    with pytest.raises(McpServerError, match="not connected"):
        runtime.call_tool("stub", "echo", {"text": "hi"})


def test_shutdown_is_idempotent(runtime: McpRuntime) -> None:
    runtime.connect(stub_config())
    runtime.shutdown()
    runtime.shutdown()


def test_streamable_http_transport(runtime: McpRuntime) -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    proc = subprocess.Popen(
        [sys.executable, str(STUB_SERVER), "--http", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    cfg = HttpServerConfig(
        name="stub-http", url=f"http://127.0.0.1:{port}/mcp", timeout=10.0
    )
    try:
        error: McpServerError | None = None
        for _ in range(40):
            try:
                runtime.connect(cfg)
                error = None
                break
            except McpServerError as exc:
                error = exc
                time.sleep(0.25)
        if error is not None:
            raise error

        result = runtime.call_tool("stub-http", "echo", {"text": "over http"})
        assert result.is_error is False
        assert result.content[0].text == "over http"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
