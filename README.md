# Application Tracker

Gmail-connected internship application tracker with follow-up drafts and a daily digest.

> Early development. See the [full build plan](docs/build-plan.md) for scope and roadmap.

## Tech stack

- **Backend:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Postgres, managed with uv
- **Frontend:** React, TypeScript, Vite, React Router, TanStack Query, Tailwind, Zod, typed client generated from OpenAPI
- **Tooling:** ruff, mypy, pytest, oxlint, Vitest, pre-commit with gitleaks, GitHub Actions

## Repo layout

```text
backend/    FastAPI app, tests, Alembic migrations
frontend/   React app and tests
docs/       build plan, architecture, threat model, decision records
infra/      Dockerfiles and local docker-compose
.github/    CI, security scans, Dependabot, templates
```

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 22 with pnpm, Docker.

```bash
# 1. Database
docker compose -f infra/docker-compose.yml up -d

# 2. Backend (http://localhost:8000, docs at /docs)
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# 3. Frontend (http://localhost:5173)
cd frontend
cp .env.example .env.local
pnpm install
pnpm dev
```

Secret scanning before every commit:

```bash
uv tool install pre-commit && pre-commit install
```

## Checks

| | Backend (`backend/`) | Frontend (`frontend/`) |
| --- | --- | --- |
| Lint | `uv run ruff check .` | `pnpm lint` |
| Types | `uv run mypy app tests` | `pnpm typecheck` |
| Tests | `uv run pytest` | `pnpm test` |

After changing an API route, run `pnpm gen:api` in `frontend/` to regenerate the typed client. CI fails if it is stale.

## License

[MIT](LICENSE)
