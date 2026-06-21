.PHONY: prepare format lint check build clean

prepare:
	uv sync --group dev
	uv run prek install

format:
	uv run ruff format .

lint:
	uv run ruff check --fix .

type-check:
	uv run ty check src/

check: format lint type-check

build:
	uv build --wheel

clean:
	rm -rf dist/ build/ src/*.egg-info
	find src/ -name '*.so' -delete
