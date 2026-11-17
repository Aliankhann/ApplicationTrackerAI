# Application Tracker: Full Build Plan

Nov 17, 2026 · @Alian Khan

## Overview

Build a Gmail-connected website that tracks internship applications automatically and drafts follow-ups, for up to 100 invited friends, in about 5 weeks at 10 to 12 hours a week. It is also a public portfolio project, so security design and repo quality matter as much as features.

Two constraints shape everything: inboxes are sensitive, so store as little as possible; and Google caps unverified apps at 100 users for the app's lifetime, so signup must be controlled.

| Decision | Choice | Why |
| --- | --- | --- |
| Backend | Python, FastAPI, SQLAlchemy, Alembic, Postgres | Fastest path to a finished product; you already know it |
| Frontend | React, TypeScript, Vite, TanStack Query | Strongest resume signal for SWE internships |
| Email providers | Gmail only in v1 | Provider interface lets Outlook plug in later |
| Classifier | Rules first, Claude small model for ambiguous emails, behind a provider interface | Accuracy on odd emails, swappable vendor |
| Stored per email | Metadata plus about 200 characters of snippet | Allows debugging and re-classifying without keeping bodies |
| First sync | Last 90 days | Covers a recruiting season, keeps first sync fast |
| Follow-ups | Drafts in v1, auto-send in v1.1 | Lower risk while the guardrails get proven |
| Digest | Daily email, user can turn it off | Works even if people forget to open the site |
| Calendar | Not in v1 | Avoids another Google scope and review surface |
| Access | Invite codes plus Google test-user allowlist | Protects the 100-user lifetime cap |
| Repo | Public from day one | Resume visibility; requires strict secret hygiene |
| Budget | Up to about $10 a month plus a domain | Always-on backend, no cold starts |

Working title: Application Tracker. Pick a real name before the domain purchase in week 5 (see Open items).

## Scope

v1 ships one complete loop: connect Gmail, see every application with a status, get follow-up drafts and a daily digest, for invited users only.

| Capability | v1 | v1.1 | Later |
| --- | --- | --- | --- |
| Google sign-in, invite codes, allowlist | Yes |  |  |
| Gmail connect and 90-day sync | Yes |  |  |
| Rules classifier plus LLM fallback | Yes |  |  |
| Dashboard, manual status fix | Yes |  |  |
| Demo mode with fake data | Yes |  |  |
| Follow-up sequences as Gmail drafts | Yes |  |  |
| Daily email digest | Yes |  |  |
| Delete my data, privacy page | Yes |  |  |
| Auto-send with caps and kill switch |  | Yes |  |
| CSV export |  | Yes |  |
| Outlook support |  |  | Yes |
| Google Calendar for interviews |  |  | Yes |

**Non-goals:** storing full email bodies, replying on a user's behalf without a draft, a mobile app, paid plans, open public signup, team accounts, scraping job boards.

**Definition of done for v1**

- [ ] A new invited user signs in, connects Gmail, and sees classified applications within 2 minutes of the first sync
- [ ] Classifier meets the accuracy targets in the Classifier section on the eval set
- [ ] Automated tests prove user A cannot read or change user B's data
- [ ] Delete my data revokes the Google token and wipes every row for that user
- [ ] Staging deploys from CI on merge, prod deploys from a tag behind a manual approval
- [ ] README, architecture diagram, threat model, and demo mode are live
- [ ] 10 friends have used it for a week with no data incident

## Architecture and repo layout

The browser only ever talks to your API; the API and a scheduled worker are the only code that touches Gmail, the LLM, and Postgres.

_Architecture diagram: to be added in `docs/architecture.md`._

A static React app calls the FastAPI backend over HTTPS with a session cookie. The API and worker share one Postgres database, and every outside call (Gmail, the LLM, email) leaves from the backend, never the browser.

**Repo layout**

```text
/backend
  app/        api, services, providers, repositories, security, jobs
  tests/
  alembic/
/frontend
  src/        pages, components, api client, demo data
/docs         architecture, threat model, decisions
/infra        Dockerfiles, compose file, deploy config
/.github      workflows, templates, dependabot
```

**Backend modules:** `api` (routes), `services` (sync, sequences, digest), `providers` (Gmail client, classifier, email, each behind an interface), `repositories` (every user-scoped query), `security` (crypto, sessions, CSRF), `jobs` (scheduler entry points).

**Tooling:** uv, ruff, mypy, and pytest on the backend; pnpm, eslint, tsc, and Vitest on the frontend; Docker Compose for local Postgres; pre-commit with gitleaks.

## Data model

Every user-owned row carries `user_id`, and every query goes through a repository layer that filters by it. Store thread-level metadata only; discard irrelevant threads immediately.

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | id, google\_sub, email, timezone, created\_at, disabled\_at | `google_sub` is the stable Google ID; unique |
| `invite_codes` | code\_hash, created\_for\_email, used\_by\_user\_id, expires\_at | Store a hash, never the code |
| `oauth_tokens` | user\_id, refresh\_token\_enc, nonce, key\_version, scopes, status | AES-GCM encrypted; status is active or revoked |
| `sync_state` | user\_id, history\_id, last\_synced\_at, initial\_sync\_done | Drives incremental sync |
| `email_threads` | user\_id, gmail\_thread\_id, subject, from\_domain, snippet, first\_message\_at, last\_message\_at, last\_sender, message\_count | Snippet capped at 200 characters; unique on user\_id plus gmail\_thread\_id |
| `classifications` | thread\_id, label, confidence, method, rule\_id, model\_version | Method is rules or llm; keeps results reproducible |
| `applications` | user\_id, company, role, status, source\_thread\_id, applied\_at, last\_activity\_at, status\_locked | `status_locked` means the user fixed it by hand; never overwrite |
| `status_events` | application\_id, from\_status, to\_status, reason, at | Powers the detail timeline |
| `sequences` | user\_id, name, steps (json), is\_default | Delays, templates, max attempts |
| `follow_up_tasks` | application\_id, step\_index, due\_at, state, gmail\_draft\_id | State: pending, drafted, sent, cancelled |
| `digest_log` | user\_id, digest\_date, sent\_at | Unique on user\_id plus digest\_date makes sends idempotent |
| `audit_log` | user\_id, action, at | Actions only (login, connect, delete); no email content |

**Statuses:** Applied, Online assessment, Interview, Offer, Rejected. Ghosted is derived (no reply after N days), not stored.

**Indexes:** `(user_id, last_message_at)`, `(user_id, status)`, unique `(user_id, gmail_thread_id)`, and `(state, due_at)` for the scheduler.

**Isolation, defense in depth:** repository layer scoping first; Postgres row-level security as a second layer if your host allows it; and a test that enumerates every route and proves cross-user access fails.

**Recipient addresses are not stored.** Draft creation fetches the To header from Gmail at that moment and discards it.

**Retention:** disconnecting Gmail deletes that user's threads and snippets; deleting the account removes every row. Backups age out on the host's schedule, which the privacy page must state honestly.

## Google and Gmail integration

Use two Google Cloud projects so staging never burns production's 100-user lifetime cap.

| Project | Publishing status | Who can sign in | Notes |
| --- | --- | --- | --- |
| tracker-staging | Testing | Your test Google accounts only | Refresh tokens expire after 7 days in Testing, which is fine for tests; localhost redirect allowed |
| tracker-prod | In production, unverified | Up to 100 users, ever | Users click through an unverified-app warning; keep the allowlist tight |

**Scopes, least privilege first**

1. Sign-in: `openid`, `email`, `profile`.
2. Connect Gmail: `gmail.readonly`, requested at the connect step, not at sign-in.
3. Follow-up drafts: `gmail.compose`, requested only when the user turns follow-ups on (incremental authorization).

Honest note: `gmail.compose` can also send mail. "Drafts only" is enforced by your code, and the privacy page should say so. Confirm in the Cloud console how Google classifies each scope for your consent screen, since policies change.

**Consent screen:** app name, support email, domain, link to the privacy page, and a short plain-language explanation of each permission. Prepare users for the "Google hasn't verified this app" screen with a 3-step guide.

**Token handling**

- Authorization code flow with `state` and PKCE; verify the ID token audience; register exact redirect URIs.
- Request offline access once; encrypt the refresh token with AES-GCM; keep access tokens in memory only.
- On `invalid_grant` (user revoked access), mark the token revoked, stop syncing, and tell the user.

**Sync algorithm**

1. Initial sync: list threads matching `newer_than:90d`, fetch metadata plus snippet, classify, keep only job-related threads, drop the rest immediately.
2. Store `history_id` from the profile after the initial sync.
3. Incremental sync every hour: `users.history.list` from the stored `history_id`; on a not-found error, fall back to a fresh 90-day sync.
4. Mark a thread as awaiting reply when its last message is from the user and it is older than the follow-up delay.
5. Use batch requests and exponential backoff; check current Gmail quota limits before launch, since they change.

**Company and role extraction:** parse the sender display name and subject first. Common applicant-tracking domains (greenhouse.io, lever.co, ashbyhq.com, myworkdayjobs.com, icims.com, smartrecruiters.com, workable.com) hide the company in the display name or subject, so those get dedicated patterns.

## Classifier

Classify cheaply with rules first, call the LLM only for what rules cannot decide, and show low-confidence results as "needs review" instead of guessing.

**Labels:** application confirmation, online assessment, interview, offer, rejection, recruiter message, irrelevant.

**Pipeline**

1. Prefilter by sender domain and keywords; drop obvious non-job mail before anything is stored.
2. Rules: ordered regex patterns, each with an id and a confidence; first strong match wins.
3. LLM fallback when no rule fires or two rules conflict. Input is sender domain, subject, and the 200-character snippet only. Output is strict JSON (label, company, role, confidence), validated against a schema.
4. Confidence below the threshold becomes "needs review"; the user's manual fix is final and locks the status.

**Provider interface:** `ClassifierProvider.classify(email) -> Result`, with `RulesProvider` and `ClaudeProvider` behind it, so the vendor can change without touching callers. Cache results by a hash of subject plus snippet so the same email never costs twice.

**Cost and safety controls:** per-user daily LLM call cap, a global monthly budget alert, and an environment kill switch that drops to rules-only.

**Prompt injection:** email text is untrusted. The LLM has no tools, returns schema-validated JSON only, and its output can never trigger a send or any other action.

**Evaluation**

- Build the labeled set from your own inbox (aim for 200 or more emails), kept outside the public repo. The repo holds synthetic fixtures modeled on real patterns.
- Targets: rejection precision at least 95% (a wrong rejection is the costliest error), overall accuracy at least 90%, LLM share of calls at most 25%.
- CI runs the rules-only eval on synthetic fixtures with a regression gate. The LLM eval runs nightly or manually, since it costs money and is not fully deterministic.

**Privacy:** only subject, domain, and snippet leave your system. State that on the privacy page, and read Google's Limited Use requirements and the LLM vendor's data terms before launch (see Open items).

## Follow-up sequences

A sequence is an ordered list of steps; the scheduler turns due steps into Gmail drafts in the original thread, and cancels everything the moment a reply arrives.

**Model**

- Default sequence: follow up at day 7, again at day 14, then stop.
- Step fields: delay in days, template, maximum attempts.
- Template variables: `{recruiter_first_name}`, `{role}`, `{company}`, `{applied_date}`, `{your_name}`. Tone presets: short and direct, warm, formal.
- Per-application controls: pause, skip a step, custom delay.

**Scheduler (runs every 15 minutes)**

1. Select applications in Applied or Online assessment where the last message is from the user and now is past the step's due time.
2. Re-fetch the thread from Gmail right before acting; if anything new arrived, cancel the task.
3. Check the send window (weekdays, 9 to 11 am in the user's timezone) and the daily draft cap.
4. Create the draft in the same thread with proper reply headers (`threadId`, `In-Reply-To`, `References`, "Re:" subject). Fetch the To address from Gmail at this moment; do not store it.
5. Mark the task drafted and include it in the next digest.

**Stop conditions:** any inbound message in the thread, status moves to Interview, Offer, or Rejected, user pauses, maximum attempts reached, Gmail disconnected, or the user already sent or edited the draft.

**Time handling:** store UTC, convert with the user's timezone, and test daylight-saving boundaries with a fake clock.

**v1.1 auto-send, opt in per sequence**

- Daily cap (default 3), maximum 2 steps per thread, weekday send window.
- 24-hour notice in the digest before anything sends ("will send tomorrow, click to cancel").
- Global kill switch, a send log for every email, and bounce detection that stops the sequence.
- Staging can only send to an allowlist of your own test addresses, enforced in code, not config alone.

## Daily email digest

Send one short email each morning at 8:00 in the user's timezone, and skip it entirely on days with nothing to report.

**Contents:** drafts waiting for review, new replies, rejections, or interview invites since the last digest, and applications with no reply after 7 or more days. Show company names and statuses only, never snippets or email text, because the digest email itself is a leak path.

**Delivery:** a transactional email provider such as Resend or Postmark (check current free-tier limits). It needs SPF, DKIM, and DMARC records on your domain, which is one more reason to buy the domain early.

**Reliability:** the `digest_log` unique key on user and date makes the job idempotent, so a retry never sends twice. Failures are logged without content and retried once.

**Opt-out:** a settings toggle, a one-click unsubscribe link, and the `List-Unsubscribe` header.

## API and frontend

The frontend is a static React app on `app.<domain>` talking to a FastAPI JSON API on `api.<domain>`; both share one registrable domain so cookies work cleanly.

**Auth and sessions**

- Backend runs the Google OAuth code flow with PKCE and `state`.
- Session cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, scoped to the parent domain. No tokens in `localStorage`.
- CORS allows only the app origin with credentials. State-changing requests also require a custom CSRF header checked against a cookie value.

**Invite gate:** the user enters a code first, then signs in with Google. If the email is not on the allowlist and the code is invalid, reject before any token is stored. Codes are long, random, single-use, hashed in the database, and rate limited.

**Endpoints**

| Method and path | Purpose |
| --- | --- |
| `GET /auth/google/start`, `GET /auth/google/callback` | Sign-in flow |
| `POST /auth/logout` | End session |
| `GET /me`, `DELETE /me` | Profile; delete my data |
| `POST /gmail/connect`, `POST /gmail/disconnect` | Connect or revoke Gmail |
| `POST /sync` | Trigger sync, returns job status |
| `GET /applications`, `PATCH /applications/{id}` | List; manual status fix |
| `GET /applications/{id}/events` | Status timeline |
| `GET/POST /sequences`, `PATCH /sequences/{id}` | Manage sequences |
| `GET /follow-ups`, `POST /follow-ups/{id}/skip` | Draft queue |
| `GET/PATCH /settings` | Digest and preferences |
| `GET /health` | Uptime check |

**Pages:** landing with demo link, invite plus sign-in, connect Gmail (plain-language consent explainer), dashboard (board by status with a table toggle), application detail with timeline, follow-up drafts queue, settings (digest, sequences, data, delete), privacy.

**Frontend stack:** React, TypeScript, Vite, React Router, TanStack Query, Tailwind with Radix primitives, Zod validation on API responses, and a typed client generated from the OpenAPI schema so frontend and backend cannot drift.

**Demo mode:** `/demo` runs the same components against a static seeded dataset, no backend calls and no sign-in. It is what recruiters see on your GitHub.

**Quality bar:** loading, empty, and error states on every page; keyboard navigation; sufficient color contrast; snippets rendered as plain text, never as HTML.

## Security and privacy

You will hold up to 100 people's inbox access, so treat security as the headline feature and document it in the repo.

| Threat | Example | Mitigation |
| --- | --- | --- |
| Token theft from the database | DB dump leaks refresh tokens | AES-GCM encryption, key kept in host secrets (not the DB), key version column, rotation plan, per-environment keys |
| Cross-user access (BOLA/IDOR) | User A requests user B's application ID | Repository layer scopes every query by user; row-level security if available; route-enumerating isolation test |
| CSRF and XSS | Malicious page triggers a request; snippet contains script | `SameSite` cookies plus CSRF header; strict CSP; snippets rendered as text only |
| Prompt injection via email | Email text tells the model to do something | Model has no tools; schema-validated output; output can never trigger sends |
| Secrets in the public repo | Key committed by accident | gitleaks pre-commit and CI, GitHub push protection, `.env.example` only |
| Log leakage | Subjects or tokens in logs | Structured logs with an allowlist of fields; never log content or tokens |
| Runaway sending | Bug floods recruiters | Drafts only in v1; caps, windows, kill switch, staging allowlist in v1.1 |
| Invite brute force | Guessing codes | Long random codes, hashed, rate limited, single use |
| OAuth misuse | Open redirect, replayed code | `state`, PKCE, exact redirect URIs, ID token audience check |
| Vulnerable dependencies | Known CVE in a package | Dependabot, `pip-audit`, `npm audit`, CodeQL |

**Delete my data:** `DELETE /me` revokes the token at Google, deletes every row for the user in one transaction, and emails a confirmation. State the backup retention window on the privacy page.

**Privacy page (plain language):** what is read, what is stored, what goes to the LLM, who can access it (only you, and you do not browse user data), how to delete everything, and a contact address. This is not legal advice; look at Canadian privacy basics (PIPEDA) before inviting people.

**Operator discipline:** the admin view shows counts only, never email content. If a token leak is suspected, rotate the key, revoke all tokens, and tell users promptly.

**Google policy flag:** Gmail data is covered by Google's API Services User Data Policy (Limited Use). Sending snippets to a third-party LLM needs checking against it before week 4.

## Testing strategy

Put the most tests where bugs are most costly: classifier, scheduler, send guardrails, and user isolation. Do not chase a coverage percentage on glue code.

| Layer | What it covers | Tools | Runs |
| --- | --- | --- | --- |
| Unit | Rules, template rendering, scheduler logic, guardrails, token encryption | pytest, time-machine (fake clock), Hypothesis | Every PR |
| Integration | API routes with real Postgres, migrations, repository scoping | pytest, Postgres service container | Every PR |
| Isolation suite | Every route, user B against user A's IDs, must fail | pytest, parametrized from the route list | Every PR |
| Classifier eval | Accuracy and precision on labeled fixtures | Custom harness | Rules on every PR; LLM nightly |
| Gmail contract | Real API against a dedicated test account | pytest, staging credentials | Nightly |
| Frontend unit | Components and hooks | Vitest, Testing Library | Every PR |
| End to end | Demo flow, sign-in, connect, dashboard, draft appears | Playwright | After each staging deploy |

**Must-have tests**

- Scheduler never drafts outside the window, never drafts after a reply, never exceeds the daily cap (property tests with a fake clock, including a daylight-saving change).
- Encryption round trip, wrong key fails, key version rotation works.
- Invite code single use, expiry, and rate limiting.
- CSRF: a state-changing request without the header is rejected.
- `DELETE /me` leaves zero rows for that user across every table.
- Gmail client sits behind an interface; unit tests use a fake, contract tests use the real API.

**QA gate before prod:** E2E on staging passes, then manual approval. After release, run a short smoke test against prod with your own account.

**Fixtures:** synthetic emails only in the repo. Real labeled emails stay in private storage.

## Environments and CI/CD

Three environments, fully separate data and secrets, with staging promoted to prod by a tag and a manual approval.

| Environment | Purpose | Data | Google project | Deploys when | Real email? |
| --- | --- | --- | --- | --- | --- |
| Local | Development | Docker Compose Postgres, fake Gmail client | tracker-staging client with localhost redirect | Manual | Never (printed to console) |
| Staging | Integration and E2E | Synthetic plus your test accounts | tracker-staging | Merge to `main` | Allowlisted test addresses only |
| Prod | Friends | Real | tracker-prod | Tag `v*` plus approval | Yes |

**Secrets:** GitHub Environments hold per-environment secrets; host env vars hold runtime secrets. Encryption keys, Google client secrets, and LLM keys differ per environment, and the LLM key has a spending limit.

**Workflows**

| File | Trigger | Jobs |
| --- | --- | --- |
| `ci.yml` | Pull request | ruff, mypy, pytest with Postgres, eslint, tsc, Vitest, build, rules-only eval |
| `security.yml` | Pull request and weekly | gitleaks, pip-audit, npm audit, CodeQL |
| `deploy-staging.yml` | Push to `main` | Build image, run migrations, deploy, then Playwright smoke |
| `deploy-prod.yml` | Tag `v*` | Requires environment approval, backup, migrate, deploy, smoke test |
| `nightly.yml` | Schedule | LLM eval, Gmail contract tests, dependency checks |

**Hosting (check current pricing before committing):** frontend on Cloudflare Pages (free); FastAPI in a container on Render or Fly.io; Postgres on Neon or Supabase; scheduled jobs through the host's cron or worker rather than GitHub Actions cron, which can run late.

**Migrations:** Alembic runs as a release step, staging first. Use expand-then-contract changes so a rollback never needs a down-migration, and take a backup before every prod migration.

**Containers:** multi-stage Dockerfile, non-root user, pinned base image.

**Branching:** trunk-based, short-lived branches, PRs required with CI green, squash merge, branch protection on `main`, SemVer tags with GitHub Releases and a changelog.

**Observability:** structured JSON logs without content, `/health`, a free uptime monitor, and error tracking only if it scrubs data. **Rollback:** redeploy the previous tag.

## GitHub polish

A recruiter should understand what this is, see it working, and trust the engineering within two minutes of opening the repo.

**README, in this order:** one-line pitch; demo link and a short GIF; screenshots; feature list; architecture diagram; security highlights (encryption, isolation, drafts-first); tech stack; quick start for local setup; test and CI badges; roadmap; license.

**Repo layout**

- `/backend` FastAPI app, tests, migrations
- `/frontend` React app and tests
- `/docs` architecture, threat model, decision records
- `/infra` Dockerfiles, compose file, deploy config
- `/.github` workflows, issue and PR templates, Dependabot config

**Docs worth writing**

- `architecture.md` and `threat-model.md`
- Short decision records: Python and FastAPI; metadata-only storage; drafts before auto-send; two Google Cloud projects; classifier provider interface; invite-only access
- `SECURITY.md` with a disclosure contact, `CONTRIBUTING.md`, MIT license

**Process signals:** Conventional Commits, small PRs with clear descriptions even though you are solo, a GitHub Projects board with one milestone per week, issues for every roadmap task, and a pinned repo on your profile.

**Hygiene before the first push:** `.env.example` only, gitleaks in pre-commit and CI, synthetic fixtures only, and no real email anywhere in history. Since the repo is public from day one, start clean rather than rewriting history later.

**Resume bullets:** write them only after launch, using numbers you can verify (active users, emails classified, measured accuracy).

## Week-by-week roadmap

Five weeks at about 12 hours each, roughly 60 hours total. Your stated capacity is higher, so the surplus is buffer for RBC weeks and surprises. Each week ends with an exit check; do not start the next week until it passes.

### Week 1 (Nov 18 to 24): Foundation, about 13 hours

- [ ] Create public repo, monorepo layout, LICENSE, README stub, `.gitignore`, `.env.example` (1h)
- [ ] gitleaks pre-commit and GitHub push protection (0.5h)
- [ ] Backend scaffold: FastAPI, pydantic-settings, `/health`, ruff, mypy, pytest (2h)
- [ ] Docker Compose Postgres, SQLAlchemy models for users, tokens, invite codes, Alembic baseline (2h)
- [ ] Frontend scaffold: Vite, React, TypeScript, Tailwind, router, OpenAPI client generation (2h)
- [ ] `ci.yml` running backend and frontend checks (2h)
- [ ] Create both Google Cloud projects and OAuth consent screens; staging client first (1.5h)
- [ ] Deploy the empty app to staging: frontend, backend, database (2h)

**Exit check:** a PR runs CI green, and the staging URL answers `/health`.

### Week 2 (Nov 25 to Dec 1): Auth and Gmail sync, about 12 hours

- [ ] Google sign-in with PKCE and the invite gate (3h)
- [ ] Sessions, CSRF header, logout, `DELETE /me` skeleton (2h)
- [ ] Token encryption module with tests (1.5h)
- [ ] Gmail connect flow with incremental consent (1.5h)
- [ ] 90-day initial sync, metadata fetch, history-based incremental sync (4h)

**Exit check:** your own inbox syncs into staging; encryption and auth tests pass.

### Week 3 (Dec 2 to 8): Classifier and dashboard, about 12 hours

- [ ] Rules engine, synthetic fixtures, eval harness with regression gate (4h)
- [ ] Company and role extraction (2h)
- [ ] Applications, status events, manual override (2h)
- [ ] Dashboard (board and table), detail page, loading and empty states (4h)

**Exit check:** you use it on your real recruiting inbox; rules accuracy is measured and written down. Also confirm with 5 friends that they apply with Gmail.

### Week 4 (Dec 9 to 15): LLM, follow-ups, digest, about 12 hours

- [ ] Provider interface, Claude provider, caching, caps, kill switch (3h)
- [ ] Sequences, templates, scheduler with fake-clock and property tests (4h)
- [ ] Gmail draft creation inside the thread (2h)
- [ ] Daily digest job, email provider, unsubscribe (3h)

**Exit check:** drafts appear in your Gmail, the digest arrives on staging, and stop-on-reply is proven by tests.

### Week 5 (Dec 16 to 22): Hardening and launch, about 12 hours

- [ ] Isolation suite across all routes, CSRF and rate-limit tests (3h)
- [ ] Delete my data end to end, verified by test (1.5h)
- [ ] Privacy page, `SECURITY.md`, threat model, decision records (2h)
- [ ] Demo mode (2h)
- [ ] Playwright E2E, prod project, domain, DNS, email authentication records (2.5h)
- [ ] README polish, architecture diagram, screenshots; invite the first 10 friends (1h)

**Exit check:** prod is live behind the approval step; 10 friends are invited.

### After launch (v1.1)

- [ ] Auto-send with caps, notice window, kill switch
- [ ] CSV export
- [ ] Raise the user count in batches of 10 to 20, watching errors and feedback between batches

## Risks, cut order, and open items

The riskiest parts are Google setup in weeks 1 and 2 and scheduler edge cases in week 4; build the fake-clock tests before the scheduler itself.

| Risk | Mitigation or fallback |
| --- | --- |
| OAuth and consent screen friction | Timebox to 4 hours; staging works in Testing mode while prod setup finishes |
| Google Limited Use policy and sending snippets to an LLM | Read the policy in week 3; fall back to rules-only if unclear |
| Classifier accuracy too low | Manual fix UI, eval-driven rule additions, "needs review" state |
| Scheduler bugs sending or drafting wrongly | Fake clock, property tests, drafts-only in v1 |
| Time lost to RBC or interviews | Use the cut order below instead of skipping sleep or prep |
| 100-user cap used up early | Invite codes, tight allowlist, staging in a separate project |
| Token or data incident | Encryption, key rotation, minimal storage, delete flow |
| Gmail quota or rate limits | Batching, backoff, hourly sync instead of real time |

**Cut order if you fall behind**

1. LLM classifier (rules-only still works)
2. Per-application overrides and tone presets
3. Email digest (move it in-app)
4. Demo polish

**Never cut:** token encryption, isolation tests, delete my data, privacy page.

**Open items**

- [ ] Pick the product name and domain registrar (check whether the GitHub Student Pack offers a free domain right now)
- [ ] Read Google's Limited Use rules and the LLM vendor's data terms before week 4
- [ ] Basic privacy review, including PIPEDA basics; this plan is not legal advice
- [ ] Choose Render or Fly.io after comparing current pricing
- [ ] Confirm the target friends apply with Gmail, not only school Outlook
- [ ] Decide the default timezone behavior for users who never set one
