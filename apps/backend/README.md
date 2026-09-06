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

## Complexité (Ruff C90 / McCabe)

`ruff check` inclut la règle `C90` (McCabe) avec un seuil de complexité
cyclomatique fixé à 15 (`[tool.ruff.lint.mccabe]` dans `pyproject.toml`). C'est
la seule métrique de complexité retenue pour ce backend ; ce même seuil
s'applique en local, dans les hooks pre-commit et en CI (job
`backend-quality`), puisqu'ils lisent tous la configuration partagée du
`pyproject.toml`.

Si une fonction dépasse légitimement ce seuil (cas résiduel documenté), la
suppression du diagnostic avec `# noqa: C901` doit obligatoirement
s'accompagner d'un commentaire expliquant pourquoi une décomposition
supplémentaire n'est pas souhaitable.

```bash
ruff check --select C90 .
```

## Migrations

```bash
alembic upgrade head
```

## Seed Admin (idempotent)

```bash
export WF_ADMIN_EMAIL=admin@example.com
export WF_ADMIN_PASSWORD='<mot-de-passe-local>'
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
