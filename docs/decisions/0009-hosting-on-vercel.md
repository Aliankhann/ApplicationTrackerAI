# 0009: Host everything on Vercel (Hobby) with one daily cron

Status: accepted (code, `vercel.json` files, and `deploy.yml` built; first deploy needs the operator)

## Context

The operator chose Vercel's Hobby plan for the frontend and the API. Limits that shape the design
(from the operator; verify them on the Usage page and in Vercel's current docs):

- a function runs at most 300 s;
- 5,000 scheduled runs per billing period; the fastest schedule is every 15 minutes, and a run can
  start up to 15 minutes late;
- 4 hours of Active CPU and 360 GB-hours of memory included;
- going over a limit pauses deployments; there is no overage billing.

There are no always-on workers and no background tasks that outlive a request. The app had assumed
a host with scheduled jobs every 10 to 15 minutes, an hourly sync, a 9 to 11 am draft window, and a
digest after 8:00 local. The operator then asked for the scheduled job to run once a day.

## Decision

- **One dispatcher, once a day.** `GET /internal/cron/tick` (`backend/vercel.json`, `0 12 * * *`,
  12:00 UTC, about 7 to 8 am in Toronto) runs everything periodic, in this order within a 240 s
  budget that keeps a 20 s margin under the 300 s limit: Gmail sync for every live token (oldest
  `last_synced_at` first, at most 60% of the budget, skipping users synced within 12 h), then the
  follow-up scheduler (until 85%), then the digest (until 100%), then the maintenance purge (once
  per UTC day, recorded in `job_runs`). Each part checks the budget before every user. The endpoint
  needs `Authorization: Bearer <CRON_SECRET>` (constant-time compare, 401 otherwise, no session,
  hidden from OpenAPI). The old `python -m app.jobs.*` entry points remain.
- **Time budgets in sync.** A sync past its deadline stops between batches, commits, frees its
  lease, and reports partial. The initial sync stores its history id and Gmail page token in
  `sync_state` and continues from there on the next run, so it spreads over daily runs and "Sync now"
  presses without duplicates.
- **"Sync now" is inline.** `POST /sync` runs the sync inside the request with a 25 s budget and
  returns `completed`, `in_progress` (the rest continues later), `already_running`, `revoked`, or
  `failed`. It is the way to get fresher data between daily runs. The per-user rate limit and the
  lease stay.
- **Daily-run rules.** Follow-up drafts may be created on any local weekday at run time
  (`FOLLOWUP_WINDOW_MODE=daily`; steps are due from the start of their local day). The 9 to 11 am
  `window` mode stays for deployments with several runs a day. The digest goes out at the daily run,
  once per local date (`DIGEST_SEND_AFTER_LOCAL_HOUR` is empty; set it to restore "after hour N").
  The daily cap and every stop condition are unchanged.
- **Serverless database.** `DB_POOL_MODE=serverless` creates the engine with `NullPool` and
  `prepare_threshold=None`, for a transaction-mode pooler (Neon or Supabase pooled URL). Nothing
  relies on session-level state across transactions: leases are rows, the only advisory lock is
  transaction-level, and row locks are transaction-level.
- **Deploys.** `.github/workflows/deploy.yml`: push to `main` deploys `staging`, a `v*` tag deploys
  `production` behind its GitHub Environment approval; migrations run before the deploy; each
  environment has its own pair of Vercel projects.
- **Dependencies.** `backend/requirements.txt` is committed and a test fails when it differs from
  `uv.lock`.

## Consequences

- **Freshness.** Gmail data updates once a day plus "Sync now". Digest and drafts also happen once
  a day. The UI says so.
- **Run count.** About 30 scheduled runs a month per environment, far below 5,000, so staging and
  production together stay well under the limit even if the quota is per account.
- **Budget limit.** If the daily budget runs out, users not reached are first in line next day
  (never-synced, then oldest). A big initial sync can take several days; "Sync now" speeds it up.
- **CPU is the scarce resource.** The sync interval is the main lever: each sync costs Active CPU
  (Gmail fetch, classification). 4 hours a month is about 8 minutes a day. Daily sync of 100 users
  is expected to fit, but check the Usage page after the first week. Raising `SYNC_MIN_GAP_HOURS`
  or leaving "Sync now" less used lowers CPU; adding runs raises it.
- **Pause on overage.** Going over a limit pauses deployments rather than billing. Watch Vercel's
  Usage page (CPU, memory, function invocations) and treat 80% as the signal to act.
- **Cold starts and no pooling.** Every invocation may open a new database connection; the pooler
  absorbs that, at some latency cost per request.
- **Late or missed runs.** Vercel may start the cron up to 15 minutes late and does not retry a failed
  run; the digest and drafts then wait for the next day. Everything is idempotent, so a manual
  `curl` of the tick with the secret is a safe re-run.
- **Cookies** need the app and API on the same registrable domain (`app.<domain>`, `api.<domain>`).
- The self-hosted Docker image in `infra/` still works but is no longer the deployment path.
