.PHONY: install test lint typecheck verify

install:
	uv sync --group dev

test:
	uv run pytest

lint:
	uv run ruff check src tests

typecheck:
	uv run pyright

verify: lint typecheck test

