# Deploying on Vercel (Hobby)

Decision and limits: [ADR 0009](decisions/0009-hosting-on-vercel.md). Nothing here has been run
against Vercel yet; items marked **verify on first deploy** are assumptions made without access to
Vercel's documentation.

You need two environments, `staging` (every push to `main`) and `production` (tags `v*`, after your
approval). Each environment has its own pair of Vercel projects and its own database.

## 1. Database (Neon or Supabase)

1. Create one Postgres database per environment.
2. Copy two connection strings: the **pooled** (transaction-mode) one for Vercel, and the **direct**
   one for migrations (GitHub). `postgres://` or `postgresql://` is fine; the app adds the psycopg
   driver itself. Keep `sslmode=require` if the provider gives it.

## 2. Vercel projects (four in total)

For each environment create two projects from this GitHub repo (or any import; deploys come from
GitHub Actions, so turn off Vercel's own Git auto-deploys in each project's Git settings):

| Project | Root directory | Framework |
| --- | --- | --- |
| `<env>-frontend` | `frontend` | Vite (build `pnpm build`, output `dist`) |
| `<env>-backend` | `backend` | Other (Python function from `api/index.py`) |

Note the **project IDs** (Settings, General) and your **team/org ID** for the GitHub secrets.
Create a Vercel **access token** (Account Settings, Tokens).

## 3. Domains and cookies

Give each project a custom domain on the **same registrable domain**: `app.<domain>` for the
frontend and `api.<domain>` for the API (staging example: `app.staging.<domain>`,
`api.staging.<domain>`). The app on `app.<domain>` must read the CSRF cookie that the API sets, so
set `COOKIE_DOMAIN=.<domain>` on the API (`.staging.<domain>` for staging). `COOKIE_DOMAIN` affects
**only the CSRF cookie** (`tracker_csrf`, `Domain=.<domain>`, Secure, SameSite=Lax, readable by
JavaScript by design). The session cookie is always host-only on the API
(`__Host-tracker_session`: Secure, HttpOnly, Path=/, no Domain, SameSite=Lax), as are the sign-in
flow cookies. Without a shared parent domain the CSRF header cannot be sent and writes fail.

## 4. Environment variables

Backend project (Settings, Environment Variables, Production scope, because each environment's
projects only ever deploy as `--prod`):

| Variable | Value / purpose |
| --- | --- |
| `ENVIRONMENT` | `staging` or `prod` |
| `DATABASE_URL` | the **pooled** (transaction-mode) URL. Not the direct one |
| `DB_POOL_MODE` | `serverless` (no app pool, no prepared statements) |
| `FRONTEND_ORIGIN` | `https://app.<domain>` (CORS and Origin check) |
| `API_BASE_URL` | `https://api.<domain>` (unsubscribe links; must be https) |
| `COOKIE_DOMAIN` | `.<domain>`; only the CSRF cookie uses it (required, see section 3) |
| `SESSION_SECRET` | `openssl rand -hex 32` (at least 32 bytes) |
| `CRON_SECRET` | `openssl rand -hex 32`; Vercel sends it as `Authorization: Bearer <value>` to the cron path (**verify on first deploy**) |
| `TOKEN_ENCRYPTION_KEYS` | `1:<base64-urlsafe 32-byte key>` (see `.env.example`) |
| `TOKEN_ENCRYPTION_CURRENT_VERSION` | `1` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | the Google OAuth client for this environment |
| `GOOGLE_REDIRECT_URI` | `https://api.<domain>/auth/google/callback` |
| `GOOGLE_CONNECT_REDIRECT_URI` | `https://api.<domain>/gmail/callback` (or leave empty for the default) |
| `ALLOWLIST_EMAILS` | comma-separated emails that may sign in without an invite |
| `TRUSTED_PROXY_COUNT` | `1` (Vercel's proxy sets the client IP in `X-Forwarded-For`; **verify on first deploy**, a wrong value breaks rate limits) |
| `MAX_USERS` | `100` |
| `LLM_ENABLED`, `ANTHROPIC_API_KEY` | leave `false` and unset until the Limited Use review is done |
| `CRON_TIME_BUDGET_SECONDS` | optional, default `240` (must stay under the 300 s function limit with margin) |
| `MANUAL_SYNC_BUDGET_SECONDS` | optional, default `25` |
| `SYNC_MIN_GAP_HOURS` | optional, default `12`; users synced more recently are skipped by the daily run |
| `FOLLOWUP_WINDOW_MODE` | optional, default `daily` |
| `DIGEST_SEND_AFTER_LOCAL_HOUR` | optional, empty = send at the daily run |

Frontend project: `VITE_API_BASE_URL=https://api.<domain>` (the workflow also passes it as a build
env). The CSP `connect-src` is filled in by the workflow from the GitHub variable `API_URL`.

## 5. Google Cloud

Per [ADR 0004](decisions/0004-two-google-cloud-projects.md), add the API-domain redirect URIs to the
OAuth client of the matching environment: `https://api.<domain>/auth/google/callback` and
`https://api.<domain>/gmail/callback`. Authorized origin: `https://app.<domain>`.

## 6. GitHub Environments

Settings, Environments: create `staging` and `production`. On `production`, add yourself as a
**required reviewer** (and optionally restrict deployment to tags). In each environment add:

- Secrets: `DATABASE_URL`, which **must be the DIRECT (non-pooled) URL**: migrations run
  `alembic upgrade head` with it, and a transaction-mode pooler is not safe for DDL. (The Vercel
  project's own `DATABASE_URL` is the **pooled** one.) Also `VERCEL_TOKEN`,
  `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID_FRONTEND`, `VERCEL_PROJECT_ID_BACKEND`.
- Variables: `API_URL` (`https://api.<domain>`), `APP_URL` (`https://app.<domain>`).

`deploy.yml` skips with a notice (and stays green) until all of these exist for the environment.
`deploy.yml` pins `VERCEL_CLI_VERSION`: check that the version exists (`npm view vercel versions`).

## 7. First deploy checklist

1. Push to `main`; watch the `Deploy` workflow: migrate, deploy API, deploy frontend, smoke test.
2. Open `https://api.<domain>/health` (200) and `https://app.<domain>/` (the landing page shows
   the API status).
3. Trigger the cron by hand: `curl -H "Authorization: Bearer $CRON_SECRET" https://api.<domain>/internal/cron/tick`
   returns counts (and 401 without the header). Then check Vercel, Cron Jobs, that it is listed.
4. Sign in, connect Gmail, press Sync now (an unfinished initial sync shows `in_progress`; press
   again or wait for the daily run).
5. Tag `v0.1.0` to deploy production; approve it in GitHub.

**Verify on first deploy** (assumptions):

- The Python runtime serves the ASGI `app` exported by `backend/api/index.py`, importing `app.*`
  from the `backend/` root, and the `/(.*)` rewrite keeps the original path for FastAPI.
- `functions.api/index.py.maxDuration: 300` is accepted on Hobby for this runtime.
- Vercel installs from the committed `backend/requirements.txt` (regenerate with
  `uv export --no-dev --no-hashes --locked --no-emit-project > requirements.txt` from `backend/`; a
  test fails when it is stale) and the bundle stays under the size limit (`.vercelignore` trims it).
- Cron runs only on production deployments (hence `--prod` for staging's own projects) and sends
  `Authorization: Bearer $CRON_SECRET` automatically when the project has `CRON_SECRET`.
- `--build-env` is accepted by `vercel deploy`, and the SPA rewrite `/((?!assets/).*)` plus the
  headers in `frontend/vercel.json` apply (check the response headers in the browser).
- The cron fires within about 15 minutes of 12:00 UTC.
- `TRUSTED_PROXY_COUNT=1` matches the `X-Forwarded-For` Vercel sends.
- Neon/Supabase pooled URL works with `DB_POOL_MODE=serverless` (no prepared statement errors).

## Changing the run time

The only place is the cron `schedule` in `backend/vercel.json` (UTC, five fields). `0 12 * * *` is
12:00 UTC, about 7 to 8 am in Toronto depending on daylight saving. Digest and drafts happen at that
run. Keep it once a day (or, if you add runs, set `FOLLOWUP_WINDOW_MODE=window` and
`DIGEST_SEND_AFTER_LOCAL_HOUR=8` to restore the time-of-day rules).

## Operating

- Watch Vercel's Usage page: Active CPU, memory, and cron invocations (about 30 a month per
  environment). Going over a Hobby limit pauses deployments.
- The tick logs one `cron.tick` line with counts and `budget_exhausted`. If it is often `1`, users
  are not all reached in one run (they continue next day; "Sync now" helps). Persistently `1` means
  the Hobby budget is too small for the user count; consider a plan with more runs.
- A migration runs before each deploy; if it fails, nothing is deployed.
