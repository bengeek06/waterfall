# rebirth

Monorepo Waterfall avec backend FastAPI et frontend Next.js.

## Structure

- apps/backend: API Python FastAPI, migrations Alembic, tests.
- apps/frontend: application web Next.js TypeScript.
- packages/api-client-ts: client TypeScript genere depuis OpenAPI.
- openapi: contrat API source de verite.

## Demarrage rapide

1. Activer l'environnement Python:

```bash
source .venv/bin/activate
```

2. Installer les dependances backend:

```bash
make install-backend
```

3. Installer les dependances frontend/workspaces:

```bash
npm install
```

## Commandes utiles

Backend:

```bash
make lint-backend
make typecheck-backend
make test-backend
make run-backend
```

Frontend:

```bash
npm run frontend:lint
npm run frontend:build
npm run frontend:dev
```

Client API TypeScript:

```bash
npm run api-client:generate
npm run api-client:build
```

Docker:

```bash
docker compose up --build
```
