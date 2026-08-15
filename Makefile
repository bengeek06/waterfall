.PHONY: install-backend lint-backend format-backend typecheck-backend test-backend run-backend hooks migrate-up compose-up install-dev lint format typecheck test run

install-backend:
	/home/benjamin/projects/rebirth/.venv/bin/python -m pip install -e ./apps/backend[dev]

lint-backend:
	cd apps/backend && ruff check .

format-backend:
	cd apps/backend && ruff format .

typecheck-backend:
	cd apps/backend && pyright

test-backend:
	cd apps/backend && pytest

run-backend:
	cd apps/backend && uvicorn waterfall.main:app --app-dir src --reload

hooks:
	pre-commit install

migrate-up:
	cd apps/backend && alembic upgrade head

compose-up:
	docker compose up --build

# Backward-compatible aliases
install-dev: install-backend
lint: lint-backend
format: format-backend
typecheck: typecheck-backend
test: test-backend
run: run-backend
