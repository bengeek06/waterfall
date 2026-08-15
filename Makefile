.PHONY: install-backend lint-backend format-backend typecheck-backend test-backend run-backend hooks migrate-up seed-admin compose-up compose-up-dev compose-up-full compose-down install-dev lint format typecheck test run

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

seed-admin:
	cd apps/backend && python -m waterfall.scripts.seed_admin

compose-up: compose-up-dev

compose-up-dev:
	docker compose -f infra/docker/docker-compose.yml up --build

compose-up-full:
	docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.full.yml up --build

compose-down:
	docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.full.yml down -v

# Backward-compatible aliases
install-dev: install-backend
lint: lint-backend
format: format-backend
typecheck: typecheck-backend
test: test-backend
run: run-backend
