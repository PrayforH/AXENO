.PHONY: install test lint typecheck verify dev-up dev-down migrate e2e web-test web-build

install:
	uv sync --group dev

test:
	uv run pytest

lint:
	uv run ruff check src tests

typecheck:
	uv run pyright

verify: lint typecheck test

dev-up:
	bash scripts/dev_up.sh

dev-down:
	bash scripts/dev_down.sh

migrate:
	uv run alembic upgrade head

e2e:
	uv run python scripts/wait_for_local_services.py
	uv run python scripts/e2e_fake_runtime.py

web-test:
	cd web/harness-console && npm test

web-build:
	cd web/harness-console && npm run build
