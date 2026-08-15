# waterfall-backend

API REST professionnelle avec FastAPI, outillage qualité, et base enterprise.

## Demarrage rapide

1. Activer l'environnement virtuel:

```bash
source /home/benjamin/projects/rebirth/.venv/bin/activate
```

2. Installer les dependances backend:

```bash
python -m pip install -e .[dev]
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
