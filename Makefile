.PHONY: prepare format lint check

prepare:
	uv sync --group dev
	uv run prek install

format:
	uv run ruff format .

lint:
	uv run ruff check --fix .

type-check:
	uv run ty check

check: format lint
