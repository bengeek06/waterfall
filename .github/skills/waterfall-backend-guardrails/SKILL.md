# waterfall-backend-guardrails

## Purpose

Provide a repository-specific backend safety protocol for Waterfall.

Use this skill when a task touches FastAPI routes, SQLAlchemy models, Pydantic schemas, Alembic migrations, OpenAPI contract, or Docker Compose runtime behavior.

## Context

Waterfall backend relies on:

- FastAPI + SQLAlchemy 2 + Pydantic v2 + Alembic
- PostgreSQL in Docker Compose and SQLite in tests
- Quality gates: ruff, pyright, pytest
- OpenAPI static contract parity check against runtime routes

## Mandatory guardrails

1. Keep migration history linear and explicit.
- Never introduce accidental parallel Alembic heads.
- Validate down_revision correctness before shipping.

2. Keep schema, models, and API aligned.
- SQLAlchemy model changes require migration impact assessment.
- Pydantic constraints must match DB constraints and business rules.
- Route changes require OpenAPI parity checks.

3. Avoid non-traceable database hotfixes.
- Prefer Alembic workflows over ad-hoc SQL patches.
- If emergency SQL is used, document and reconcile with migration history immediately.

4. Preserve transactional integrity.
- No partial writes on business errors.
- Explicit rollback behavior when mutating multiple tables.

5. Keep runtime diagnostics actionable.
- Error messages should be explicit and useful to callers.
- Distinguish API failure from post-action refresh failure when relevant.

6. Use repository virtual environment consistently.
- Run Python tooling from `.venv/` to avoid host-path drift.
- Prefer explicit binaries: `/home/benjamin/projects/waterfall/.venv/bin/...`.

## Verification checklist

### A. API and contracts

- Verify status codes and response payload consistency.
- Verify auth and ownership boundaries.
- Run targeted OpenAPI parity checks when routes change.

### B. Data and migrations

- Run migration upgrade on the target environment.
- If migration modified, test downgrade feasibility.
- Check tables/constraints exist as expected after upgrade.

### C. Quality gates

- Run ruff on impacted backend files.
- Run pyright for backend package.
- Run targeted pytest for changed scope.
- Run full backend pytest when change is cross-cutting.

### D. Compose/runtime checks (if incident)

- Inspect service status and API logs.
- Validate health endpoint responsiveness.
- Confirm database schema state before blaming network/CORS.

## Standard command set

From apps/backend:

- ruff check .
- /home/benjamin/projects/waterfall/.venv/bin/pyright
- /home/benjamin/projects/waterfall/.venv/bin/pytest
- /home/benjamin/projects/waterfall/.venv/bin/pytest --no-cov tests/<target_file>.py
- /home/benjamin/projects/waterfall/.venv/bin/alembic upgrade head

From repository root:

- make lint-backend
- make typecheck-backend
- make test-backend
- make migrate-up
- docker compose -f infra/docker/docker-compose.yml ps
- docker compose -f infra/docker/docker-compose.yml logs --tail=120 api

## Expected output behavior

When used by an agent:

- State what was verified vs. assumed.
- List exact commands executed.
- Report residual risks and unverified zones.
- If blocked by environment drift, propose the smallest safe recovery plan first.
