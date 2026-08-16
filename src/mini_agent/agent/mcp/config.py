import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ...config import CONFIG_DIR, WORKDIR

DEFAULT_TOOL_TIMEOUT = 60.0

MCP_CONFIG_PATHS: list[Path] = [
    CONFIG_DIR / "mcp.json",
    WORKDIR / ".mini-agent" / "mcp.json",
]

_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def expand_vars(value: str) -> str:
    return _VAR_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)


def _expand_required(field_name: str, value: str) -> str:
    expanded = expand_vars(value)
    unset = _VAR_PATTERN.findall(expanded)
    if unset:
        raise ValueError(
            f'"{field_name}" references unset environment variable(s): '
            + ", ".join(unset)
        )
    return expanded


@dataclass
class StdioServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TOOL_TIMEOUT


@dataclass
class HttpServerConfig:
    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TOOL_TIMEOUT
    client_id: str | None = None
    client_secret: str | None = None


ServerConfig = StdioServerConfig | HttpServerConfig


def _parse_entry(name: str, entry: object) -> ServerConfig:
    if not isinstance(entry, dict):
        raise ValueError("must be an object")
    timeout = entry.get("timeout", DEFAULT_TOOL_TIMEOUT)
    if not isinstance(timeout, int | float) or timeout <= 0:
        raise ValueError('"timeout" must be a positive number')
    entry_type = entry.get("type")
    if entry_type == "http":
        url = entry.get("url")
        if not isinstance(url, str) or not url:
            raise ValueError('http server requires a "url" string')
        headers = entry.get("headers", {})
        if not isinstance(headers, dict):
            raise ValueError('"headers" must be an object')
        client_id = entry.get("client_id")
        client_secret = entry.get("client_secret")
        return HttpServerConfig(
            name=name,
            url=expand_vars(url),
            headers={str(k): expand_vars(str(v)) for k, v in headers.items()},
            timeout=float(timeout),
            client_id=(
                _expand_required("client_id", str(client_id)) if client_id else None
            ),
            client_secret=(
                _expand_required("client_secret", str(client_secret))
                if client_secret
                else None
            ),
        )
    if entry_type is not None:
        raise ValueError(f'unsupported type "{entry_type}"')
    command = entry.get("command")
    if not isinstance(command, str) or not command:
        raise ValueError('stdio server requires a "command" string')
    args = entry.get("args", [])
    if not isinstance(args, list):
        raise ValueError('"args" must be a list')
    env = entry.get("env", {})
    if not isinstance(env, dict):
        raise ValueError('"env" must be an object')
    return StdioServerConfig(
        name=name,
        command=command,
        args=[str(a) for a in args],
        env={str(k): expand_vars(str(v)) for k, v in env.items()},
        timeout=float(timeout),
    )


def load_mcp_servers(
    paths: list[Path] | None = None,
) -> tuple[dict[str, ServerConfig], list[str]]:
    servers: dict[str, ServerConfig] = {}
    errors: list[str] = []
    for path in paths if paths is not None else MCP_CONFIG_PATHS:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: {exc}")
            continue
        entries = None
        if isinstance(data, dict):
            entries = data.get("mcpServers", data.get("servers"))
        if not isinstance(entries, dict):
            errors.append(f'{path}: expected an object with an "mcpServers" object')
            continue
        for name, entry in entries.items():
            try:
                servers[str(name)] = _parse_entry(str(name), entry)
            except ValueError as exc:
                errors.append(f"{path}: server {name!r}: {exc}")
    return servers, errors
