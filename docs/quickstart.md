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

**Update**

```bash
mini update
```

On macOS and Linux this installs the latest release with `uv`. Windows cannot
replace `mini.exe` while it runs, so `mini update` prints the installer command
to run instead.

## Authenticate

Add a provider to `~/.mini-agent/config.toml`:

```toml
[providers.gateway]
name = "My Gateway"
base_url = "https://gateway.example.com"
api_key_env = "GATEWAY_API_KEY"
```

Then put its key in `~/.mini-agent/.env`:

```bash
GATEWAY_API_KEY=...
```

See [Providers](providers.md) for multiple providers and switching.

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
- [Providers](providers.md) - provider setup and switching.
- [Config](config.md) - provider, model, and reasoning effort defaults.
- [MCP](mcp.md) - connect MCP servers for extra tools.
