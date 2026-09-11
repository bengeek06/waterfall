"""Pure domain packages: no SQLAlchemy, no FastAPI, no I/O.

Modules under this package model business rules in plain Python so they can be
exercised (and proven) without a database or an HTTP stack. Persistence and
transport adapters live in ``waterfall.models`` / ``waterfall.api`` and depend on
this package, never the other way round.
"""
