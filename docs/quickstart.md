# Quickstart

## Install

**Pre-built**

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/kowyo/mini-agent/main/scripts/install.sh | bash

# Windows
powershell -c "irm https://raw.githubusercontent.com/kowyo/mini-agent/main/scripts/install.ps1 | iex"
```

**From source**

```bash
uv tool install git+https://github.com/kowyo/mini-agent.git@main
```

## Authenticate

Set an API key before launching:

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
mini
```

Or persist in `~/.mini-agent/.env`. See [Providers](providers.md) for gateway configuration.

## First session

Start mini-agent in your project directory:

```bash
cd /path/to/project
mini
```

Type a request and press Enter:

```text
Summarize this repository
```

## Next steps

- [Usage](usage.md) - CLI flags, slash commands, and keyboard shortcuts.
- [Providers](providers.md) - authentication and gateway setup.
- [Config](config.md) - model and reasoning effort defaults.
- [MCP](mcp.md) - connect MCP servers for extra tools.
