# Repository Guidelines

## Project Structure

```text
.
├── docs/                    # Documentation
├── src/mini_agent/          # Python package
│   ├── agent/               # Agent runtime and tools
│   ├── cli/                 # CLI and terminal UI
│   └── config.py            # Configuration and API client
├── tests/                   # Test suite
├── Makefile                 # Development commands
├── pyproject.toml           # Project configuration
├── uv.lock                  # Dependency lockfile
└── uv.toml                  # uv configuration
```

## Development Commands

Use `uv` for dependency management and command execution.

- `make prepare`: sync the project and dev dependencies, then install pre-commit hooks.
- `uv run mini`: run the CLI locally from the working tree.
- `make check`: run formatting, linting, type checking, and tests.
- `make build`: build the wheel into `dist/`.
- `make clean`: remove build outputs, package metadata, and compiled extension artifacts.

## Testing Guidelines

Before validating changes, run `make clean`.
