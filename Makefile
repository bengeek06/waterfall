COMPOSE := docker compose -f infra/docker/docker-compose.yml
COMPOSE_FULL := docker compose -f infra/docker/docker-compose.yml -f infra/docker/docker-compose.full.yml
BACKEND := apps/backend
PYTHON := $(CURDIR)/.venv/bin/python
RUFF := $(PYTHON) -m ruff
PYRIGHT := $(PYTHON) -m pyright
PYTEST := $(PYTHON) -m pytest
ALEMBIC := $(PYTHON) -m alembic

.DEFAULT_GOAL := help

.PHONY: help venv install install-backend install-frontend \
	lint lint-backend lint-frontend format format-backend \
	typecheck typecheck-backend typecheck-frontend \
	test test-backend test-frontend build build-frontend gen-client \
	dev run run-backend run-frontend db-up db-down up up-full down stop logs \
	migrate-up seed-admin hooks clean clean-docker distclean \
	install-dev compose-up compose-up-dev compose-up-full compose-down

help:  ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---- Install ----
venv:  ## Create the root Python virtualenv if it does not exist
	@test -x .venv/bin/python || python3 -m venv .venv
install: install-backend install-frontend  ## Install backend + frontend deps
install-backend: venv  ## Install backend (editable + dev extras)
	$(PYTHON) -m pip install -e './apps/backend[dev]'
install-frontend:  ## Install JS workspace deps
	npm ci

# ---- Quality ----
lint: lint-backend lint-frontend  ## Lint backend + frontend
lint-backend:  ## Ruff check (backend)
	cd $(BACKEND) && $(RUFF) check .
lint-frontend:  ## ESLint (frontend)
	npm run frontend:lint
format: format-backend  ## Format backend (ruff)
format-backend:
	cd $(BACKEND) && $(RUFF) format .
typecheck: typecheck-backend typecheck-frontend  ## Type-check backend + frontend
typecheck-backend:  ## Pyright (backend)
	cd $(BACKEND) && $(PYRIGHT)
typecheck-frontend:  ## tsc --noEmit (frontend)
	cd apps/frontend && npx tsc --noEmit
test: test-backend test-frontend  ## Test backend + frontend
test-backend:  ## Pytest (backend)
	cd $(BACKEND) && $(PYTEST)
test-frontend:  ## Vitest (frontend)
	npm run frontend:test

# ---- Build / contract ----
build: build-frontend  ## Build frontend (incl. api client)
build-frontend:
	npm run frontend:build
gen-client:  ## Regenerate the OpenAPI TypeScript client
	npm run openapi:bundle
	npm run api-client:generate

# ---- Run (native dev) ----
run: dev  ## Alias for 'dev'
dev:  ## Run backend + frontend natively (Ctrl-C stops both)
	@$(PYTHON) scripts/run_with_env.py bash -c 'backend_pid=; frontend_pid=; cleanup() { trap - EXIT INT TERM; kill "$$backend_pid" "$$frontend_pid" 2>/dev/null || true; wait "$$backend_pid" "$$frontend_pid" 2>/dev/null || true; }; trap cleanup EXIT INT TERM; (cd $(BACKEND) && $(PYTHON) -m uvicorn waterfall.main:app --app-dir src --reload --host "$${APP_HOST:-0.0.0.0}" --port "$${APP_PORT:-8000}") & backend_pid=$$!; npm run frontend:dev & frontend_pid=$$!; wait -n "$$backend_pid" "$$frontend_pid"'
run-backend:  ## Run backend only (uvicorn --reload)
	@$(PYTHON) scripts/run_with_env.py bash -c 'exec "$(PYTHON)" -m uvicorn waterfall.main:app --app-dir "$(BACKEND)/src" --reload --host "$${APP_HOST:-0.0.0.0}" --port "$${APP_PORT:-8000}"'
run-frontend:  ## Run frontend only (next dev)
	@$(PYTHON) scripts/run_with_env.py npm run frontend:dev

# ---- Docker ----
db-up:  ## Start Postgres only (detached) for native dev
	$(COMPOSE) up -d postgres
db-down:  ## Stop Postgres
	$(COMPOSE) stop postgres
up:  ## Start base stack (api + db), foreground
	$(COMPOSE) up --build
up-full:  ## Start full stack (api, db, frontend, observability)
	$(COMPOSE_FULL) up --build
down:  ## Stop stack (containers removed, volumes kept)
	$(COMPOSE_FULL) down
stop: down  ## Alias for 'down'
logs:  ## Follow stack logs
	$(COMPOSE) logs -f

# ---- DB / tooling ----
migrate-up:  ## Apply Alembic migrations
	cd $(BACKEND) && $(ALEMBIC) upgrade head
seed-admin:  ## Seed the admin user
	cd $(BACKEND) && $(PYTHON) -m waterfall.scripts.seed_admin
hooks:  ## Install pre-commit hooks (pre-commit + pre-push)
	pre-commit install

# ---- Clean ----
clean:  ## Remove Python/Next caches and build outputs
	find . -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
	find apps/backend -type d -name '*.egg-info' -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf apps/backend/.pytest_cache apps/backend/.ruff_cache apps/backend/.coverage apps/backend/htmlcov
	rm -rf apps/frontend/.next apps/frontend/.turbo
	rm -rf packages/api-client-ts/dist
clean-docker:  ## Stop stack and DELETE volumes (DB data lost)
	$(COMPOSE_FULL) down -v --remove-orphans
distclean: clean clean-docker  ## Also remove node_modules and .venv
	rm -rf node_modules apps/frontend/node_modules packages/api-client-ts/node_modules .venv

# ---- Backward-compatible aliases ----
install-dev: install-backend
compose-up: up
compose-up-dev: up
compose-up-full: up-full
compose-down: clean-docker
