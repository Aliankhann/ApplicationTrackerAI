# 0001: Python and FastAPI for the backend

Status: accepted (implemented)

## Context

The project has about five weeks at 10 to 12 hours a week, and it is also a public portfolio
piece. The backend does Gmail API work, a rules classifier built on regular expressions, scheduled
jobs, and a JSON API for a React app. The author already knows Python well, and the work is
dominated by integration and text processing, not raw throughput. Up to 100 users means load is
not a constraint.

## Decision

Use Python 3.13 with FastAPI, SQLAlchemy 2, Alembic, and Postgres, managed with `uv`. Type the
code with mypy in strict mode and lint with ruff. FastAPI generates an OpenAPI schema, from which
the frontend client types are generated (`pnpm gen:api`), so the two sides cannot drift silently.

## Consequences

- Fast path to a finished product, with a strong typing and testing toolchain (pytest, Hypothesis).
- Pydantic validation at the API edge and OpenAPI for free.
- Jobs (sync, scheduler, digest) are plain Python modules that share the models and repositories
  with the API, so there is one data layer to secure.
- Python is not the fastest runtime. That is acceptable at this scale; the Gmail API and network
  calls dominate.
- Sync SQLAlchemy sessions keep the code simple; async is not used.
- Postgres features (advisory locks, JSONB, partial unique indexes) are used directly and tie the
  project to Postgres.
