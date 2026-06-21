# Repository Guidelines

## Project Structure

```text
.
├── src/mini_agent/          # Python package
│   ├── __main__.py          # CLI entry point
│   ├── cli/                 # command handling and terminal UI
│   └── agent/               # agent runtime, prompts, variables, tools
├── docs/                    # user and configuration docs
├── scripts/                 # install helpers
├── pyproject.toml           # package metadata and tool config
├── Makefile                 # development commands
└── uv.lock                  # locked dependency graph
```

## Development Commands

Use `uv` for Python environment and command execution.

- `make prepare`: sync dependencies, including the dev group, and install pre-commit hooks.
- `uv run mini`: run the CLI locally from the working tree.
- `make check`: run formatting, linting, and type checking.
- `make build`: build a wheel into `dist/`.
- `make clean`: remove build outputs and compiled extension artifacts.

## Testing Guidelines

Before testing new changes, run `make clean` to remove generated outputs. Then run `make check` at minimum. When adding tests, place them under `tests/`, mirror package paths where practical, and name files `test_*.py`. Prefer focused tests for CLI behavior, agent orchestration, and tool handlers, plus regression tests for fixed bugs.
