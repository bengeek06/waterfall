.PHONY: install-dev lint format typecheck test run hooks migrate-up compose-up

install-dev:
	/home/benjamin/projects/rebirth/.venv/bin/python -m pip install -e .[dev]

lint:
	ruff check .

format:
	ruff format .

typecheck:
	pyright

test:
	pytest

run:
	uvicorn waterfall.main:app --app-dir src --reload

hooks:
	pre-commit install

migrate-up:
	alembic upgrade head

compose-up:
	docker compose up --build
