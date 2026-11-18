# Architecture

> Stub. The full diagram lands in week 5. See [build-plan.md](build-plan.md#architecture-and-repo-layout).

- A static React app (`frontend/`) talks only to the FastAPI API (`backend/`) over HTTPS with a session cookie.
- The API and a scheduled worker share one Postgres database.
- Every outside call (Gmail, the LLM, the email provider) leaves from the backend, never the browser.

## Security headers

- The API sets its own headers (strict CSP, nosniff, no-referrer, HSTS outside local) in `backend/app/middleware.py`.
- The SPA's headers come from the host via `frontend/public/_headers` (Cloudflare Pages format). The deploy step must replace the `__API_ORIGIN__` placeholder in the CSP `connect-src` with the real API origin (for example `https://api.<domain>`). The deploy workflow (US-05) must substitute it in `dist/_headers` and then run `DEPLOY=1 pnpm check:deploy` (from `frontend/`), which fails while the placeholder remains.
