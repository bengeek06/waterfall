# Cross-application tests

This directory contains assets and test entry points that span the backend and frontend.
Application-specific tests stay in `apps/backend/tests` and `apps/frontend/src`.

## Layout

- `data/`: stable, versioned fixtures shared by integration and future E2E tests.
- `integration/`: cross-application scenarios that exercise the HTTP API and persisted planning state.
- `e2e/`: reserved for browser tests. They are intentionally not collected until the planning UI is stable; browser coverage is tracked separately in issue #89.

## Fixture rules

- Keep fixtures small and readable for functional tests.
- Generate large datasets in test setup, outside the measured benchmark interval.
- Do not encode credentials, environment-specific IDs, or timestamps that are not part of the assertion.
- Document the business state represented by each fixture, especially draft, validated, reference, and read-only states.
