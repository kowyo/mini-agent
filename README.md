# uv devcontainer template

This project is a minimal Python template built for development with `uv` and VS Code Dev Containers.

## What this project includes

- Python package application layout
- Dependency management with `uv`
- Development container configuration in `.devcontainer/`
- Code formatting and linting with `ruff`
- Git hooks with `prek`
- Commit message validation with `commitizen`

## Project structure

```text
.
├── .devcontainer/      # Dev Container configuration
├── Makefile            # Common development commands
├── prek.toml           # Git hook configuration
├── pyproject.toml      # Project metadata and tooling config
├── src/
│   └── starter/        # Example Python package
└── uv.lock             # Locked dependency versions
```

## Available commands

```bash
make prepare  # install dependencies and Git hooks
make format   # format code with ruff
make lint     # lint and auto-fix code with ruff
make check    # run format and lint
```
