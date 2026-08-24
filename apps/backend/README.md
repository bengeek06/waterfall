# waterfall-backend

API REST professionnelle avec FastAPI, outillage qualité, et base enterprise.

## Demarrage rapide

1. Activer l'environnement virtuel:

```bash
source ../../.venv/bin/activate
```

2. Installer les dependances backend:

```bash
python -m pip install -e '.[dev]'
```

3. Lancer les controles:

```bash
ruff check .
ruff format --check .
pyright
pytest
```

4. Lancer l'API:

```bash
uvicorn waterfall.main:app --app-dir src --reload
```

## Migrations

```bash
alembic upgrade head
```

## Seed Admin (idempotent)

```bash
WF_ADMIN_EMAIL=admin@example.com \
WF_ADMIN_PASSWORD=admin1234 \
waterfall-seed-admin
```

## Endpoints auth principaux

- POST /auth/register
- POST /auth/token
- POST /auth/refresh
- GET /auth/me
- POST /auth/me/password
- GET /auth/users (admin)
- PATCH /auth/users/{user_id}/status (admin)
- PATCH /auth/users/{user_id}/role (admin)
