import json
from pathlib import Path

import pytest

from mini_agent.agent.mcp.config import (
    DEFAULT_TOOL_TIMEOUT,
    HttpServerConfig,
    StdioServerConfig,
    expand_vars,
    load_mcp_servers,
)


def write_config(path: Path, servers: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}))
    return path


def test_missing_files_yield_no_servers(tmp_path: Path) -> None:
    servers, errors = load_mcp_servers([tmp_path / "mcp.json"])
    assert servers == {}
    assert errors == []


def test_parses_stdio_entry(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "mcp.json",
        {
            "chrome": {
                "command": "npx",
                "args": ["-y", "chrome-devtools-mcp"],
                "env": {"DEBUG": "1"},
                "timeout": 30,
            }
        },
    )
    servers, errors = load_mcp_servers([path])
    assert errors == []
    assert servers == {
        "chrome": StdioServerConfig(
            name="chrome",
            command="npx",
            args=["-y", "chrome-devtools-mcp"],
            env={"DEBUG": "1"},
            timeout=30.0,
        )
    }


def test_defaults(tmp_path: Path) -> None:
    path = write_config(tmp_path / "mcp.json", {"srv": {"command": "server"}})
    servers, _ = load_mcp_servers([path])
    assert servers["srv"].args == []
    assert servers["srv"].env == {}
    assert servers["srv"].timeout == DEFAULT_TOOL_TIMEOUT


def test_parses_http_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_PAT", "token123")
    path = write_config(
        tmp_path / "mcp.json",
        {
            "github": {
                "type": "http",
                "url": "https://api.example.com/mcp",
                "headers": {"Authorization": "Bearer ${GITHUB_PAT}"},
            }
        },
    )
    servers, errors = load_mcp_servers([path])
    assert errors == []
    assert servers == {
        "github": HttpServerConfig(
            name="github",
            url="https://api.example.com/mcp",
            headers={"Authorization": "Bearer token123"},
        )
    }


def test_http_entry_requires_url(tmp_path: Path) -> None:
    path = write_config(tmp_path / "mcp.json", {"srv": {"type": "http"}})
    servers, errors = load_mcp_servers([path])
    assert servers == {}
    assert len(errors) == 1


def test_project_overrides_home_per_server(tmp_path: Path) -> None:
    home = write_config(
        tmp_path / "home" / "mcp.json",
        {"a": {"command": "home-a"}, "b": {"command": "home-b"}},
    )
    project = write_config(
        tmp_path / "project" / "mcp.json", {"a": {"command": "project-a"}}
    )
    servers, errors = load_mcp_servers([home, project])
    assert errors == []
    assert servers["a"].command == "project-a"
    assert servers["b"].command == "home-b"


def test_invalid_entries_collected_as_errors(tmp_path: Path) -> None:
    path = write_config(
        tmp_path / "mcp.json",
        {
            "no-command": {"args": []},
            "bad-type": {"type": "websocket", "command": "x"},
            "bad-timeout": {"command": "x", "timeout": -1},
            "ok": {"command": "server"},
        },
    )
    servers, errors = load_mcp_servers([path])
    assert list(servers) == ["ok"]
    assert len(errors) == 3
    assert any("'no-command'" in e for e in errors)


def test_invalid_json_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text("{not json")
    servers, errors = load_mcp_servers([path])
    assert servers == {}
    assert len(errors) == 1


def test_env_var_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_TOKEN", "secret")
    monkeypatch.delenv("UNSET_VAR", raising=False)
    path = write_config(
        tmp_path / "mcp.json",
        {"srv": {"command": "server", "env": {"TOKEN": "${MY_TOKEN}"}}},
    )
    servers, _ = load_mcp_servers([path])
    assert servers["srv"].env == {"TOKEN": "secret"}
    assert expand_vars("${UNSET_VAR}") == "${UNSET_VAR}"
