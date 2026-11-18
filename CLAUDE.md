# Application Tracker

Gmail-connected internship application tracker. Public repo, invite-only app, up to 100 users.
Scope and roadmap: `docs/build-plan.md`. Stories and acceptance criteria: `docs/backlog.md`.

## Stack
- Backend (`backend/`): Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Postgres, uv
- Frontend (`frontend/`): React, TypeScript 5.9, Vite, React Router, TanStack Query, Tailwind, Zod, pnpm

## Structure
- `backend/app/`: `api` (routes), `services`, `providers` (Gmail, classifier, email behind interfaces),
  `repositories` (all user-scoped queries), `security`, `jobs`; models in `models.py`
- `backend/tests/`, `backend/alembic/versions/`
- `frontend/src/`: `pages`, `components`, `api` (generated `schema.d.ts`, do not edit), `demo`

## Commands
- Backend, from `backend/`: `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests eval && uv run pytest`
- Migrations: `uv run alembic revision --autogenerate -m "..."`, then `uv run alembic upgrade head` and `downgrade base` to check both directions
- Frontend, from `frontend/`: `pnpm lint && pnpm typecheck && pnpm test && pnpm build`
- After changing any API route: `pnpm gen:api` in `frontend/` (CI fails if the client is stale)
- Local Postgres: `docker compose -f infra/docker-compose.yml up -d`, or `service postgresql start` in cloud sessions
- Migration test creates a throwaway database; if it skips, run `su postgres -c "psql -c 'ALTER USER tracker CREATEDB'"` (CI user already can)

## Rules
- Every query on user-owned data goes through `repositories/` and filters by `user_id`.
- Never store full email bodies, recipient addresses, or snippets longer than 200 characters.
- Never log email content, subjects, snippets, or tokens. Refresh tokens are AES-GCM encrypted.
- State-changing routes require the CSRF header. Render email text as plain text only.
- No secrets in code or fixtures; only `.env.example`. Test fixtures are synthetic, never real email.
- Gmail and the LLM sit behind interfaces; tests use fakes, never the real APIs.
- Each story: tests for every acceptance criterion, all checks green, small PR, Conventional Commit title.
