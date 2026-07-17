.PHONY: prepare format lint type-check test check build clean

prepare:
	uv sync --group dev
	uv run prek install

format:
	uv run ruff format .

lint:
	uv run ruff check --fix .

type-check:
	uv run ty check src/

test:
	uv run pytest tests

check: format lint type-check test

build:
	uv build --wheel

clean:
	rm -rf dist/ build/ src/*.egg-info
