# Architecture

> Stub. The full diagram lands in week 5. See [build-plan.md](build-plan.md#architecture-and-repo-layout).

- A static React app (`frontend/`) talks only to the FastAPI API (`backend/`) over HTTPS with a session cookie.
- The API and a scheduled worker share one Postgres database.
- Every outside call (Gmail, the LLM, the email provider) leaves from the backend, never the browser.
