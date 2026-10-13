# mini-agent

https://github.com/user-attachments/assets/155e9256-8138-410b-9253-97d33e031045

A minimal agent running in your terminal.

## Installation

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

## Documentation

See [docs/](docs/).

## Development

```bash
git clone https://github.com/kowyo/mini-agent
cd mini-agent
make prepare
uv run mini
```
