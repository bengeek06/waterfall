# Plan de migration vers monorepo apps/backend + apps/frontend

## Objectif

Mettre en place une structure professionnelle et evolutive tout en gardant un risque faible:

1. API FastAPI reste stable et livrable pendant la migration.
2. Frontend Next.js est ajoute sans perturber les usages backend existants.
3. CI passe a des checks separes backend/frontend/contrat OpenAPI.

## Decision de structure

Cible de depot:

- apps/backend: code FastAPI, tests backend, migrations, docker backend.
- apps/frontend: Next.js + TypeScript.
- packages/api-client-ts: client TypeScript genere depuis OpenAPI.
- openapi: contrat API source de verite.
- infra: compose et outillage infra multi-apps.
- docs: conventions et decisions d architecture.

## Strategie pragmatique en 4 phases

### Phase 1 - Introduire le frontend sans casser le backend (PR 1)

But: ajouter apps/frontend et les workspaces Node sans deplacer le backend tout de suite.

Actions:

1. Creer apps/frontend (Next.js + TypeScript).
2. Ajouter package manager workspace (pnpm prefere) a la racine.
3. Ajouter scripts npm de base pour frontend.
4. Laisser pyproject/backend a la racine pour conserver le pipeline actuel.

Validation:

1. Backend: ruff, pyright, pytest passent comme aujourd hui.
2. Frontend: build, lint et typecheck passent.
3. Aucune regression API.

### Phase 2 - Client TypeScript genere depuis OpenAPI (PR 2)

But: fiabiliser la couche d appel API frontend.

Actions:

1. Creer packages/api-client-ts.
2. Ajouter generation depuis openapi/import_v1.yaml.
3. Exposer une API typed consommee par apps/frontend.

Validation:

1. Generation deterministe (pas de diff non attendu).
2. Front compile avec types OpenAPI.
3. Ecran test appelle auth/import/projects via client genere.

### Phase 3 - Deplacer le backend vers apps/backend (PR 3)

But: finaliser la structure cible monorepo.

Actions detaillees:

1. Deplacer:
   - src -> apps/backend/src
   - tests -> apps/backend/tests
   - migrations -> apps/backend/migrations
   - alembic.ini -> apps/backend/alembic.ini
   - pyproject.toml -> apps/backend/pyproject.toml
   - Dockerfile -> apps/backend/Dockerfile
2. Mettre a jour les chemins dans:
   - apps/backend/pyproject.toml (pytest, coverage, ruff src paths)
   - apps/backend/alembic.ini (script_location, prepend_sys_path)
   - Makefile racine (targets backend scopes)
   - .pre-commit-config.yaml (commands backend explicites)
   - .github/workflows/ci.yml (working-directory backend pour jobs Python)
   - docker-compose.yml (build context / Dockerfile backend)
3. Ajouter un README backend dedie.

Validation:

1. Depuis la racine: make lint-backend, make test-backend, make run-backend OK.
2. Alembic upgrade head OK.
3. Docker compose API+Postgres OK.

### Phase 4 - CI pro par domaines (PR 4)

But: pipeline rapide et robuste.

Actions:

1. Job backend (python quality + tests).
2. Job frontend (lint + typecheck + tests).
3. Job contract (validation OpenAPI + generation client TS).
4. Optionnel: e2e smoke (auth -> import -> projects -> export).

Validation:

1. Jobs independants et lisibles.
2. Temps CI reduit via filtrage par paths.
3. Quality gates obligatoires sur PR.

## Conventions de commandes (cible)

Depuis la racine:

- make install-backend
- make lint-backend
- make test-backend
- make run-backend
- make install-frontend
- make lint-frontend
- make test-frontend
- make generate-api-client
- make ci

## Impacts identifies dans l etat actuel

Fichiers a ajuster pendant la migration backend:

1. pyproject.toml actuel configure src/tests en racine.
2. alembic.ini pointe migrations en racine.
3. Dockerfile copie src depuis la racine.
4. docker-compose.yml build context racine.
5. Makefile utilise des commandes backend non scopees.
6. .pre-commit-config.yaml execute pyright/pytest depuis la racine.
7. .github/workflows/ci.yml installe et teste le package racine.
8. README.md documente uniquement l execution backend en racine.

## Ordre de livraison recommande

1. PR 1: frontend minimal + workspace Node.
2. PR 2: client TS genere OpenAPI.
3. PR 3: migration physique backend vers apps/backend.
4. PR 4: CI finale multi-domaines.

## Risques et mitigation

Risque 1: casse des paths outils Python.
Mitigation: migration backend dans une PR dediee + check complet ruff/pyright/pytest/alembic.

Risque 2: divergence contrat OpenAPI vs impl.
Mitigation: generation client TS en CI + test smoke endpoint.

Risque 3: complexite initiale CI.
Mitigation: garder CI backend existante jusqu a PR 3, puis bascule progressive.

## Definition of Done globale

1. Arborescence cible active avec apps/backend et apps/frontend.
2. Front utilise client TS genere depuis OpenAPI.
3. CI verte sur backend, frontend, contract.
4. Documentation de run locale et conventions a jour.
