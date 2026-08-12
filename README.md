# waterfall

API REST professionnelle avec FastAPI, outillage qualité, et base enterprise.

## Demarrage rapide

1. Activer l'environnement virtuel:

```bash
source .venv/bin/activate
```

2. Installer les dependances du projet:

```bash
python -m pip install -e .[dev]
```

3. Lancer les controles:

```bash
ruff check .
ruff format .
pyright
pytest
```

4. Lancer l'API:

```bash
uvicorn waterfall.main:app --app-dir src --reload
```

## Endpoints

- `GET /health`
- `GET /health/ready`
- `POST /auth/register`
- `POST /auth/token`
- `GET /auth/me`
- `GET /metrics`

## Migrations

```bash
alembic upgrade head
```

## Docker Compose

```bash
docker compose up --build
```
