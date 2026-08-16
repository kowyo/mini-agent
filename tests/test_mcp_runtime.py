import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from mcp_types import TextContent

from mini_agent.agent.mcp.config import StdioServerConfig
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
