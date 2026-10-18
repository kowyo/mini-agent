import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from mcp_types import CallToolResult, ImageContent, TextContent

from mini_agent.agent.mcp import tools as mcp_tools
from mini_agent.agent.mcp.config import StdioServerConfig
from mini_agent.agent.mcp.runtime import McpRuntime
from mini_agent.agent.mcp.tools import _map_result, _tool_name, setup_mcp
from mini_agent.agent.tools.base import MAX_OUTPUT, ToolError
from mini_agent.agent.tools.handlers import TOOL_HANDLERS
from mini_agent.agent.tools.schemas import TOOLS
from mini_agent.agent.transcript import ImageBlock, TextBlock

STUB_SERVER = Path(__file__).parent / "mcp_stub_server.py"


def text_result(text: str, is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)], is_error=is_error
    )


def test_tool_name_namespacing_and_sanitization() -> None:
    assert _tool_name("chrome", "take_screenshot") == "mcp__chrome__take_screenshot"
    assert _tool_name("my server", "do.things") == "mcp__my_server__do_things"


def test_map_text_result() -> None:
    result = CallToolResult(
        content=[
            TextContent(type="text", text="one"),
            TextContent(type="text", text="two"),
        ]
    )
    assert _map_result(result) == "one\ntwo"


def test_map_image_result_matches_read_file_shape() -> None:
    result = CallToolResult(
        content=[
            TextContent(type="text", text="screenshot"),
            ImageContent(type="image", data="aGk=", mime_type="image/png"),
        ]
    )
    assert _map_result(result) == (
        TextBlock(text="screenshot"),
        ImageBlock(data="aGk=", mime_type="image/png"),
    )


def test_map_error_result() -> None:
    mapped = _map_result(text_result("kaboom", is_error=True))
    assert mapped == ToolError("kaboom")


def test_map_empty_result() -> None:
    assert _map_result(CallToolResult(content=[])) == "(no content)"


def test_map_truncates_giant_output() -> None:
    mapped = _map_result(text_result("x" * (MAX_OUTPUT + 1)))
    assert isinstance(mapped, str)
    assert len(mapped) == MAX_OUTPUT + len(mcp_tools._TRUNCATION_MARKER)
    assert mapped.endswith(mcp_tools._TRUNCATION_MARKER)


@pytest.fixture
def registry() -> Iterator[None]:
    tools_len = len(TOOLS)
    handler_names = set(TOOL_HANDLERS)
    yield
    del TOOLS[tools_len:]
    for name in set(TOOL_HANDLERS) - handler_names:
        del TOOL_HANDLERS[name]


def test_setup_registers_tools_and_handlers(
    monkeypatch: pytest.MonkeyPatch, registry: None
) -> None:
    cfg = StdioServerConfig(
        name="stub", command=sys.executable, args=[str(STUB_SERVER)], timeout=10.0
    )
    _runtime = McpRuntime()
    monkeypatch.setattr(mcp_tools, "_runtime", _runtime)
    monkeypatch.setattr(mcp_tools, "load_mcp_servers", lambda: ({"stub": cfg}, []))

    try:
        lines = setup_mcp()
        assert lines == []
        status = mcp_tools.server_statuses
        assert len(status) == 1
        assert status[0].name == "stub"
        assert status[0].error is None
        assert {"echo", "fail", "sleep", "die"} == set(status[0].tools)
        assert "mcp__stub__echo" in TOOL_HANDLERS
        schema = next(t for t in TOOLS if t.name == "mcp__stub__echo")
        assert schema.parameters["properties"]["text"]["type"] == "string"

        assert TOOL_HANDLERS["mcp__stub__echo"](text="hi") == "hi"
        failure = TOOL_HANDLERS["mcp__stub__fail"]()
        assert isinstance(failure, ToolError)
    finally:
        _runtime.shutdown()


def test_setup_reports_failed_server(
    monkeypatch: pytest.MonkeyPatch, registry: None
) -> None:
    cfg = StdioServerConfig(name="bad", command="mini-agent-no-such-command")
    _runtime = McpRuntime()
    monkeypatch.setattr(mcp_tools, "_runtime", _runtime)
    monkeypatch.setattr(mcp_tools, "load_mcp_servers", lambda: ({"bad": cfg}, []))

    try:
        lines = setup_mcp()
        assert len(lines) == 1
        assert "bad" in lines[0]
        assert len(mcp_tools.server_statuses) == 1
        assert mcp_tools.server_statuses[0].name == "bad"
        assert mcp_tools.server_statuses[0].error is not None
        assert all(not name.startswith("mcp__") for name in TOOL_HANDLERS)
    finally:
        _runtime.shutdown()
