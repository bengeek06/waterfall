---
name: waterfall-frontend-guardrails
description: Repository-specific frontend guardrails for Waterfall Next.js, React, TypeScript, API, session, accessibility, and validation work.
---

# waterfall-frontend-guardrails

## Purpose

Provide repository-specific frontend safety rules for Waterfall (Next.js 16, React 19, TypeScript, Vitest, ESLint).

Use this skill for any task touching UI behavior, API calls from frontend, session/auth handling, routing, or generated API types.

## Context

Waterfall frontend relies on:

- Next.js App Router (v16)
- React 19 + TypeScript
- ESLint (`eslint-config-next` core-web-vitals + typescript)
- Vitest + Testing Library (jsdom)
- Generated API client package: `@rebirth/api-client`

Backend coupling specifics:

- API base URL from `NEXT_PUBLIC_API_BASE_URL`, fallback to `http://localhost:8000`
- Auth strategy: in-memory access token in `src/lib/session.ts`
- Refresh flow implemented in `src/lib/backend.ts` with `refreshInFlight` deduplication

## Mandatory guardrails

1. Preserve frontend/backend contract compatibility.
- Keep payload field names, status handling, and auth assumptions aligned with backend.
- Treat OpenAPI-generated types as source of truth for API data shapes.

2. Preserve session and refresh safety.
- Keep single-flight refresh behavior (`refreshInFlight`) intact.
- Distinguish API errors, auth-expired errors, and network errors in UI messaging.

3. Prevent UX dead-ends.
- Loading/error states must be explicit and actionable.
- Destructive actions require confirmation and clear feedback.

4. Keep React state transitions safe.
- Avoid stale closures, missing hook dependencies, and double submissions.
- Guard async flows against partial UI state updates after failures.

5. Respect Next.js 16 environment constraints.
- Before any frontend code change, read `apps/frontend/AGENTS.md` and the relevant guide in `apps/frontend/node_modules/next/dist/docs/` as required by that file.

## Verification checklist

### A) Type and contract checks

- Ensure API calls match generated types from `@rebirth/api-client`.
- Validate request/response/error handling paths for changed screens.

### B) UI behavior checks

- Verify loading states, empty states, and errors are visible and meaningful.
- Verify navigation/redirect behavior on session expiry.

### C) Accessibility and interaction

- Check labels, aria attributes, keyboard interaction, and focus-sensitive flows.

### D) Quality gates

- Run frontend lint, tests, and build for impacted scope.
- Prefer targeted tests first, full suite when cross-cutting changes are involved.

## Standard command set

From repository root:

- npm run frontend:lint
- npm run frontend:test
- npm run frontend:build

From apps/frontend:

- npm run lint
- npm run test
- npm run build
- npm run test -- src/<target_file>.test.ts or src/<target_file>.test.tsx

If API/runtime incident is suspected:

- docker compose -f infra/docker/docker-compose.yml ps
- docker compose -f infra/docker/docker-compose.yml logs --tail=120 api
- curl -sf http://127.0.0.1:8000/health

## Expected output behavior

When used by an agent:

- State what was verified vs. assumed.
- List exact commands executed (or explicitly not executed in dry-run).
- Report residual risks and unverified zones.
- If blocked, propose the smallest safe recovery path first.
