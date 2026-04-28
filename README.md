# mini-agent

<img width="1063" height="418" alt="image" src="https://github.com/user-attachments/assets/792da9af-7472-4231-a1ca-17d1a73e0841" />

A minimal agent running in your terminal.

## Installation

**macOS / Linux**

```bash
curl -fsSL https://raw.githubusercontent.com/kowyo/mini-agent/v0.12.0/scripts/install.sh | bash
```

**Windows**

```powershell
powershell -c "irm https://raw.githubusercontent.com/kowyo/mini-agent/v0.12.0/scripts/install.ps1 | iex"
```

**From source**

Prerequisites: A Python C extension development environment.

See the [mypyc getting started guide](https://mypyc.readthedocs.io/en/latest/getting_started.html) for setup instructions.

```bash
uv tool install git+https://github.com/kowyo/mini-agent.git@v0.12.0
```

## Development

```bash
git clone https://github.com/kowyo/mini-agent
cd mini-agent
make prepare
uv run mini
```
