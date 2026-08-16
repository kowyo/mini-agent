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


@dataclass
class StdioServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TOOL_TIMEOUT


ServerConfig = StdioServerConfig


def _parse_entry(name: str, entry: object) -> ServerConfig:
    if not isinstance(entry, dict):
        raise ValueError("must be an object")
    timeout = entry.get("timeout", DEFAULT_TOOL_TIMEOUT)
    if not isinstance(timeout, int | float) or timeout <= 0:
        raise ValueError('"timeout" must be a positive number')
    entry_type = entry.get("type")
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
        entries = data.get("mcpServers") if isinstance(data, dict) else None
        if not isinstance(entries, dict):
            errors.append(f'{path}: expected an object with an "mcpServers" object')
            continue
        for name, entry in entries.items():
            try:
                servers[str(name)] = _parse_entry(str(name), entry)
            except ValueError as exc:
                errors.append(f"{path}: server {name!r}: {exc}")
    return servers, errors
