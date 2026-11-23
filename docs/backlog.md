# Backlog: epics and user stories

This file turns [build-plan.md](build-plan.md) into small stories, each one testable on its own.
Work through them in order. Each week ends with an **integration check** that ties that week's
stories together before the next week starts.

## How we work

Every story follows the same loop, so nothing reaches `main` untested.

1. **Pick** the next story whose dependencies are done. Create a GitHub issue for it if one
   doesn't exist yet.
2. **Branch** from `main`: `feat/US-12-invite-gate`, `fix/US-12-...`, `chore/...`.
3. **Write the tests first** from the acceptance criteria, and watch them fail.
4. **Build** until the tests pass.
5. **Run every check locally** (see the README): ruff, mypy, pytest, lint, typecheck, Vitest, build.
6. **Open a PR** that names the story (`Closes #<issue>`, `US-12`). Keep it small: one story,
   ideally under about 400 changed lines.
7. **Merge** only when CI and Security are green and every acceptance criterion is ticked.
   Squash merge with a Conventional Commit title (`feat(auth): invite gate (US-12)`).

### Definition of ready (before starting a story)

- Acceptance criteria are written and testable.
- Dependencies are merged.
- Any manual setup (Google console, host, DNS) is done or is its own story.

### Definition of done (before merging a story)

- Every acceptance criterion has an automated test, or a written manual check when it truly
  can't be automated (for example, Google console setup).
- CI and Security are green.
- No secrets, real emails, or personal data in the diff, fixtures, or logs.
- New tables are user-scoped through the repository layer, and new routes are added to the
  isolation suite (once US-60 exists).
- Docs or `.env.example` are updated if behavior or config changed.

### Story format

Each story has an ID, a user story, **acceptance criteria (AC)**, the **tests** that prove them,
**dependencies**, and an **estimate**. "Manual" means a person checks it by hand once.

### Status key

`[ ]` not started · `[~]` in progress · `[x]` done

---

## Epic 0: Foundation (week 1)

Goal: a PR runs CI green, and the staging URL answers `/health`.

### [x] US-01 Monorepo boilerplate
As a developer, I want a working skeleton for the backend, frontend, and CI so every later story
has somewhere to go.
- **AC:** `/health` returns `{"status":"ok"}`; the baseline migration applies and rolls back;
  the frontend builds and shows API status; CI runs every check on each PR.
- **Tests:** `tests/test_health.py`, `LandingPage.test.tsx`, migration up/down step in CI.
- **Estimate:** done.

### [ ] US-02 Local secret scanning and push protection
As the owner of a public repo, I want secrets blocked before they leave my machine.
- **AC:** `pre-commit install` works; committing a fake AWS-style key is blocked by gitleaks;
  GitHub push protection and secret scanning are on in repo settings.
- **Tests:** Manual: commit a dummy key on a throwaway branch and confirm it is blocked, then
  delete the branch. CI gitleaks job already runs on every PR.
- **Depends on:** US-01 · **Estimate:** 0.5h

### [ ] US-03 Branch protection on `main`
As the maintainer, I want `main` to accept only green, reviewed-by-CI changes.
- **AC:** Direct pushes to `main` are blocked; PRs need the CI `backend`, `frontend`, and Security
  checks to pass; squash merge only.
- **Tests:** Manual: a PR with a failing test cannot be merged.
- **Depends on:** US-01 · **Estimate:** 0.25h

### [ ] US-04 Google Cloud projects and consent screens
As the operator, I want separate staging and prod Google projects so testing never uses up
prod's 100-user cap.
- **AC:** `tracker-staging` (Testing mode, your test accounts added) and `tracker-prod` exist;
  each has an OAuth client with exact redirect URIs; staging allows the localhost redirect;
  client IDs and secrets live only in host or GitHub secrets.
- **Tests:** Manual checklist; confirmed by US-11's sign-in test.
- **Depends on:** none · **Estimate:** 1.5h

### [~] US-05 Staging deploy
_Done in the repo (see [ADR 0009](decisions/0009-hosting-on-vercel.md), [deploy.md](deploy.md)):
Vercel Hobby chosen; `.github/workflows/deploy.yml` (push to `main` deploys `staging`: migrate,
deploy API and frontend with the pinned Vercel CLI, smoke test; skips cleanly until configured);
`backend/vercel.json` and `backend/api/index.py`; `frontend/vercel.json` with the SPA rewrite and
CSP; the daily cron tick. Needs the operator: Neon/Supabase database, four Vercel projects,
domains, env vars, GitHub `staging` environment secrets, then the first deploy and the "verify on
first deploy" checklist._

As the developer, I want every merge to `main` to deploy to staging.
- **AC:** Host chosen (Vercel Hobby) and recorded as a decision; `deploy.yml` runs migrations
  against the staging database, then deploys the API and the frontend to their Vercel projects;
  the staging `/health` returns 200; the staging landing page shows "API status: ok".
- **Tests:** A post-deploy smoke step in the workflow calls `/health`, fetches the landing page and
  checks its CSP header, and fails the job on any failure. Repo tests cover the cron endpoint, the
  time budgets, `vercel.json`, and `requirements.txt` freshness.
- **Depends on:** US-01 · **Estimate:** 2h

### Integration check, week 1
- [ ] Open a trivial PR: CI is green, and it can't merge while red.
- [ ] Merge it: staging redeploys, and the staging landing page shows the API as up.

---

## Epic 1: Sign-in and access control (week 2)

Goal: only invited people can sign in, and sessions are safe against CSRF.

### [x] US-10 Invite code management
As the operator, I want to create single-use invite codes so I control who uses the 100 slots.
- **AC:** A CLI command creates a long random code (at least 128 bits), prints it once, and
  stores only its hash with an expiry; optional `created_for_email`.
- **Tests:** Unit: the stored value is a hash, not the code; two codes never collide in 10k
  generations; expiry is set.
- **Depends on:** US-01 · **Estimate:** 0.5h
- **Update (two-phase claim):** `invite list` shows id prefix, state (available, held, claimed,
  used, expired, revoked), expiry and bound email, never the code; `invite revoke <id-prefix>`
  marks a code unusable. Tests: `tests/test_invite_codes.py` (CLI section).

### [x] US-11 Google sign-in with PKCE
_Built and tested against a local fake Google (signed ID tokens, PKCE, JWKS). A live round trip
waits on the Google Cloud projects (US-04); see `backend/.env.example` for the config to set._

As an invited user, I want to sign in with Google so I don't need another password.
- **AC:** `GET /auth/google/start` redirects to Google with `state`, a PKCE challenge, and only
  `openid email profile`; the callback rejects a missing or mismatched `state`; the ID token's
  audience and issuer are verified; a user row is created or found by `google_sub`.
- **Tests:** Integration with a fake Google token endpoint: happy path, bad `state`, wrong
  audience, replayed code.
- **Depends on:** US-04, US-10 · **Estimate:** 2h

### [x] US-12 Invite gate
As the operator, I want uninvited people rejected before anything about them is stored.
- **AC:** A new user must present a valid code or be on the allowlist; an invalid, used, or
  expired code is rejected and no user or token row is written; a valid code is marked used by
  that user; returning users skip the gate; the code endpoint is rate limited.
- **Tests:** Integration: valid code, reused code, expired code, allowlisted email without a
  code, no row written on rejection, rate limit returns 429.
- **Depends on:** US-10, US-11 · **Estimate:** 1h
- **Update (two-phase claim):** a code is held for 10 minutes when entered (409 `invite_in_use`
  if another browser holds it), claimed by the new pending user at Google sign-up (24 h,
  `INVITE_CLAIM_HOURS`), and used only when Gmail is connected (`account_setup_completed`).
  Unfinished sign-ups are deleted by the daily tick and the code reopens. Sign in
  (`/auth/google/start?mode=signin`) never uses a code; an unknown Google account gets
  `no_account`. Allowlisted emails skip the code in either mode. Holds do not count toward the
  cap; claims do. Tests: `tests/test_signin.py`, `test_gmail_connect.py`,
  `test_invite_lifecycle.py`.

### [x] US-13 Sessions and logout
As a signed-in user, I want to stay signed in safely and be able to sign out.
- **AC:** The session cookie is `HttpOnly`, `Secure` (outside local), `SameSite=Lax`, scoped to
  the parent domain; `GET /me` returns the profile when signed in and 401 otherwise;
  `POST /auth/logout` ends the session server side; nothing goes in `localStorage`.
- **Tests:** Integration: cookie flags, `/me` with and without a session, a cookie used after
  logout is rejected.
- **Depends on:** US-11 · **Estimate:** 1h

### [x] US-14 CSRF protection
As a user, I want malicious sites unable to act on my behalf.
- **AC:** Every state-changing route (POST, PATCH, DELETE) requires an `X-CSRF-Token` header that
  matches the CSRF cookie; CORS allows only the app origin with credentials.
- **Tests:** Integration, parametrized over every state-changing route: no header gives 403,
  wrong header gives 403, correct header passes. A request from another origin fails CORS.
- **Depends on:** US-13 · **Estimate:** 1h

### [x] US-15 Invite and sign-in pages
As an invited friend, I want a clear page to enter my code and sign in.
- **AC:** An invite page takes a code and then starts sign-in; errors for a bad code are shown in
  plain language; loading, error, and success states exist; the page is keyboard accessible.
- **Tests:** Vitest: form validation, error message on 4xx, redirect on success.
- **Depends on:** US-12 · **Estimate:** 1h
- **Update (two-phase claim):** `/sign-in` first offers Sign up and Sign in. Sign up is the code
  step then "Continue with Google"; Sign in goes straight to Google. A pending user sees a
  "Finish setup: connect Gmail" screen with the time the invite is held until. Errors:
  `invite_in_use`, `invite_expired`, `no_account`.

### [x] US-16 Audit log
As the operator, I want a record of sensitive actions without storing any email content.
- **AC:** Login, logout, Gmail connect and disconnect, and delete are written to `audit_log` with
  user ID, action, and time only.
- **Tests:** Integration: each action writes exactly one row with no extra fields.
- **Depends on:** US-13 · **Estimate:** 0.5h
- **Notes:** `audit_log` and `repositories/audit.record` exist; logout, disconnect, and delete write
  entries. TODO: US-11 must call `record(..., LOGIN)` and US-31 `record(..., GMAIL_CONNECTED)`;
  follow-ups enable (US-61/65) uses `FOLLOWUPS_ENABLED`. `purge_audit` (365 days) needs a scheduled
  caller. `user_id` has no FK so the anonymous `account_deleted` row can outlive the user.

### Integration check, auth
- [ ] On staging, your test account signs in with a fresh invite code, sees `/me`, logs out.
- [ ] A second account without a code is refused, and the database has no row for it.

---

## Epic 2: Token security (week 2)

Goal: refresh tokens are useless to anyone who steals the database.

### [x] US-20 Token encryption module
As the operator, I want refresh tokens encrypted at rest with a key the database never sees.
- **AC:** AES-GCM with a fresh random nonce per encryption; key loaded from settings; ciphertext,
  nonce, and `key_version` stored; plaintext never logged.
- **Tests:** Unit: round trip; wrong key fails; tampered ciphertext fails; two encryptions of the
  same token differ; Hypothesis property test over random tokens.
- **Depends on:** US-01 · **Estimate:** 1h

### [x] US-21 Key rotation
As the operator, I want to rotate the encryption key without logging everyone out.
- **AC:** Settings can hold the current key plus older keys by version; decrypt picks the key by
  `key_version`; a rotate command re-encrypts all tokens with the current key.
- **Tests:** Unit and integration: encrypt with v1, rotate to v2, decrypt succeeds, v1 key can
  then be removed.
- **Depends on:** US-20 · **Estimate:** 0.5h

### Integration check, tokens
- [ ] A row in `oauth_tokens` on staging contains no readable token text.

---

## Epic 3: Gmail connect and sync (week 2)

Goal: your own inbox syncs into staging, keeping only job-related threads.

### [x] US-30 Gmail client interface and fake
As a developer, I want Gmail behind an interface so tests never call Google.
- **AC:** A `GmailClient` protocol covers list threads, get thread metadata, get profile, history
  list, and (later) create draft; a `FakeGmailClient` serves synthetic threads from fixtures.
- **Tests:** Unit tests for the fake; mypy checks both implement the protocol.
- **Depends on:** US-01 · **Estimate:** 0.5h

### [x] US-31 Connect Gmail with incremental consent
As a signed-in user, I want to connect Gmail as a separate step so I understand what I'm granting.
- **AC:** `POST /gmail/connect` starts a consent flow for `gmail.readonly` only, with offline
  access; the refresh token is stored encrypted (US-20); a plain-language explainer page comes
  before the Google screen.
- **Tests:** Integration with a fake token endpoint: token is stored encrypted, requested scopes
  are exactly as expected, CSRF is required.
- **Depends on:** US-13, US-20 · **Estimate:** 1.5h

### [x] US-32 Initial 30-day sync
As a newly connected user, I want my last 30 days of job email pulled in.
- **AC:** Lists threads with `newer_than:{initial_sync_days}d` (default 30); fetches metadata plus snippet; the snippet is
  capped at 200 characters; non-job threads are discarded and never written; `history_id` and
  `initial_sync_done` are saved; re-running is idempotent (unique on user and thread).
- **Tests:** Integration with the fake client: only job threads stored, snippet length capped,
  running twice creates no duplicates.
- **Depends on:** US-30, US-31, US-40 (prefilter) · **Estimate:** 2h

### [x] US-33 Incremental sync
As a user, I want new email picked up regularly without a full resync (once a day on Vercel Hobby, plus "Sync now"; see ADR 0009).
- **AC:** Uses `history.list` from the stored `history_id`; a not-found response triggers a fresh
  initial sync; `invalid_grant` marks the token revoked and stops syncing for that user.
- **Tests:** Integration with the fake: new thread appears, expired history falls back,
  revoked token stops sync and flags the user.
- **Depends on:** US-32 · **Estimate:** 1.5h

### [x] US-34 Manual sync and status
As a user, I want to trigger a sync and see whether it is running.
- **AC:** `POST /sync` starts a sync (one at a time per user) and returns a job status; the
  frontend shows progress and the last synced time.
- **Tests:** Integration: a second request while running returns the existing job, not a new one.
- **Depends on:** US-32 · **Estimate:** 0.5h

### [x] US-35 Disconnect Gmail
As a user, I want to disconnect Gmail and have my synced data removed.
- **AC:** `POST /gmail/disconnect` revokes the token at Google, marks it revoked, and deletes that
  user's threads and snippets.
- **Tests:** Integration: zero thread rows after disconnect; revoke endpoint called once.
- **Depends on:** US-31 · **Estimate:** 0.5h
- **Notes:** Revocation sits behind `TokenRevoker` (`providers/google/revoke.py`); production wiring
  raises "not configured" (503 on disconnect) until US-31 adds the real Google call.

### Integration check, week 2 exit
- [ ] Your own inbox syncs into staging; only job-related threads are stored.
- [ ] Encryption and auth test suites pass in CI.

---

## Epic 4: Classifier (weeks 3 and 4)

Goal: every synced thread gets a label, measured against targets.

### [x] US-40 Prefilter
As the system, I want obvious non-job mail dropped before anything is stored.
- **AC:** A sender-domain and keyword prefilter returns keep or drop; ATS domains
  (greenhouse.io, lever.co, ashbyhq.com, myworkdayjobs.com, icims.com, smartrecruiters.com,
  workable.com) are always kept.
- **Tests:** Unit on synthetic fixtures: newsletters dropped, ATS mail kept.
- **Depends on:** US-01 · **Estimate:** 0.5h

### [x] US-41 Rules engine
As the system, I want ordered regex rules to label most emails without an LLM.
- **AC:** Labels: confirmation, online assessment, interview, offer, rejection, recruiter
  message, irrelevant; each rule has an ID and confidence; first strong match wins; conflicts
  are reported as ambiguous; the result records `method=rules` and `rule_id`.
- **Tests:** Unit per rule with positive and negative fixtures.
- **Depends on:** US-40 · **Estimate:** 2h

### [x] US-42 Eval harness and regression gate
As a developer, I want accuracy measured on every PR so rule changes can't silently get worse.
- **AC:** Synthetic labeled fixtures (at least 100) in the repo; a harness reports overall
  accuracy, rejection precision, and per-label numbers; CI fails if numbers drop below the
  stored baseline; real labeled emails stay outside the repo.
- **Tests:** The harness itself runs in CI; a deliberately broken rule fails the gate.
- **Depends on:** US-41 · **Estimate:** 1.5h
- **Known gap from US-41 QA:** rules are precise but miss rejection wording they weren't tuned
  on (0 of 10 unseen rejections caught; all went to review, none mislabelled). Seed the eval set
  with held-out phrasings such as "chosen to go with other candidates", "will not be offering you
  a position", "unable to take your application further", "decided to close your application",
  "won't be extending an offer", "decided not to pursue your candidacy", "regret that we cannot
  offer you the position", "decided to pass on your application", "will not be continuing with
  yours", "not selected for the next stage". Keep a held-out split that rules are never tuned on.

### [x] US-43 Company and role extraction
As a user, I want each application to show the right company and role.
- **AC:** Parses sender display name and subject; dedicated patterns for each ATS domain;
  returns unknown rather than guessing.
- **Tests:** Unit fixtures per ATS; unknown cases return none.
- **Depends on:** US-41 · **Estimate:** 2h

- **Known gap from QA:** only runs on threads the prefilter and classifier kept. Staffing agencies
  and job boards ("HireFast Staffing", "Job Hunt Weekly") come back as the company because nothing
  in the email separates them from an employer; the manual fix in US-51 covers these. Two-word
  names with no org suffix or corroboration ("Maple Grove") are deliberately returned as None.

### [x] US-44 Classifier provider interface
As a developer, I want classifiers swappable without touching callers.
- **AC:** `ClassifierProvider.classify(email) -> Result`; `RulesProvider` implements it; results
  cached by a hash of subject plus snippet.
- **Tests:** Unit: same input hits the cache; callers depend only on the interface.
- **Depends on:** US-41 · **Estimate:** 0.5h

### [x] US-45 Claude fallback provider
As a user, I want odd emails classified well instead of marked unknown.
- **AC:** Called only when no rule fires or rules conflict; input is domain, subject, and snippet
  only; output is strict JSON validated against a schema; invalid output falls back to "needs
  review"; the model has no tools and its output never triggers an action.
- **Tests:** Unit with a fake LLM: valid JSON, invalid JSON, injection-style snippet that tries to
  change the label format. Nightly eval against the real API.
- **Depends on:** US-44, Limited Use review (open item) · **Estimate:** 1.5h
- **Note:** Built and off by default. Before enabling: complete the Google Limited Use review and
  the vendor data-terms check (Open items).

### [x] US-46 LLM cost and safety controls
_Before enabling: (1) usage rows are written in the sync transaction, so a rolled-back batch can
undercount spend by one batch; move `LlmControls.record` to its own short committed session if
the budget must be exact. (2) Update the privacy page's "Currently nothing" line in the same
change that turns the LLM on._

As the operator, I want LLM spend capped and switchable off.
- **AC:** Per-user daily call cap; an environment kill switch forces rules-only; LLM share of
  calls is reported by the eval.
- **Tests:** Unit: cap reached falls back to rules; kill switch on means zero LLM calls.
- **Depends on:** US-45 · **Estimate:** 1h

### [x] US-47 Needs review threshold
As a user, I want unsure results flagged instead of guessed.
- **AC:** Confidence below the threshold shows as "needs review" and never changes a status.
- **Tests:** Unit: low-confidence result leaves the status untouched.
- **Depends on:** US-44 · **Estimate:** 0.5h

### Integration check, classifier
- [ ] Rules accuracy on your real inbox is measured and written down (private notes).
- [ ] Targets: rejection precision at least 95%, overall accuracy at least 90%, LLM share at
  most 25%.

---

## Epic 5: Applications and dashboard (week 3)

Goal: you use it on your real recruiting inbox.

### [x] US-50 Applications from threads
As a user, I want each job thread turned into one application with a status.
- **AC:** A classified thread creates or updates an application; statuses are Applied, Online
  assessment, Interview, Offer, Rejected; status only moves forward unless the user changes it;
  every change writes a `status_events` row.
- **Tests:** Integration: confirmation then interview then rejection produces three events;
  duplicates on the same thread don't create a second application.
- **Depends on:** US-41, US-43 · **Estimate:** 1.5h

### [x] US-51 Manual status fix
As a user, I want to correct a wrong status and have it stick.
- **AC:** `PATCH /applications/{id}` sets status and `status_locked`; later syncs never overwrite
  a locked status; the change appears in the timeline.
- **Tests:** Integration: lock, then sync a rejection email, status unchanged.
- **Depends on:** US-50 · **Estimate:** 0.5h

### [x] US-52 Applications API
As the frontend, I want to list applications and their timelines.
- **AC:** `GET /applications` (filter by status, sort by last activity), `GET
  /applications/{id}/events`; ghosted is derived (no reply after N days), not stored.
- **Tests:** Integration: filters, sort, ghosted calculation with a fake clock.
- **Depends on:** US-50 · **Estimate:** 0.5h

### [x] US-53 Dashboard board and table
As a user, I want to see all my applications by status at a glance.
- **AC:** A board grouped by status with a table toggle; loading, empty, and error states;
  keyboard navigable; snippets rendered as plain text, never HTML.
- **Tests:** Vitest: each state renders; a snippet containing `<script>` renders as text.
- **Depends on:** US-52 · **Estimate:** 2.5h

### [x] US-54 Application detail page
As a user, I want one application's history and a way to fix its status.
- **AC:** Shows company, role, status, and timeline; the status control calls US-51 and updates
  the page without a reload.
- **Tests:** Vitest: timeline renders; status change calls the API with the CSRF header.
- **Depends on:** US-51, US-53 · **Estimate:** 1.5h

### Integration check, week 3 exit
- [ ] Sign in, connect, sync, and see your real applications on staging.
- [ ] Confirm with 5 friends that they apply with Gmail.

---

## Epic 6: Follow-up drafts (week 4)

Goal: drafts appear in your Gmail, and stop-on-reply is proven by tests.

### [x] US-60 Route isolation suite
As the operator, I want proof that no user can touch another user's data.
- **AC:** A test enumerates every route from the app's router and, for each one that takes an
  ID, calls it as user B with user A's IDs; every call returns 404 or 403. Adding a route without
  isolation coverage fails CI.
- **Tests:** The suite itself; a deliberately unscoped query makes it fail.
- **Depends on:** US-52 · **Estimate:** 1.5h (moved earlier than the plan so every later route is
  covered from day one)

### [x] US-61 Sequences
`/sequences` routes wait on sessions (US-13). Normalize pasted `\r\n` to `\n` in the route layer._

As a user, I want a default follow-up plan I can adjust.
- **AC:** Default sequence: day 7, day 14, stop; `GET/POST /sequences`, `PATCH /sequences/{id}`;
  steps validated (delay, template, max attempts).
- **Tests:** Integration: default created on first use; invalid steps rejected.
- **Depends on:** US-13 · **Estimate:** 1h

### [x] US-62 Template rendering
As a user, I want follow-ups written with the right names and dates.
- **AC:** Variables `{recruiter_first_name}`, `{role}`, `{company}`, `{applied_date}`,
  `{your_name}`; a missing value falls back to safe text, never a raw placeholder; tone presets.
- **Tests:** Unit: every variable, every preset, missing values.
- **Depends on:** US-61 · **Estimate:** 0.5h

### [x] US-63 Fake clock and scheduler tests first
As a developer, I want the scheduler's rules written as tests before the scheduler exists.
- **AC:** Property tests with a fake clock: never drafts outside weekdays 9 to 11 am local time (`window` mode) or on a local weekend (`daily` mode, the default since ADR 0009);
  never drafts after an inbound reply; never exceeds the daily cap; correct across a
  daylight-saving change.
- **Tests:** These tests, failing until US-64 lands.
- **Depends on:** US-61 · **Estimate:** 1h

### [x] US-64 Scheduler
As a user, I want due follow-ups turned into drafts automatically.
- **AC:** Runs from the daily cron tick (every 15 minutes in the original plan); selects Applied or Online assessment applications whose last
  message is from the user and whose step is due; re-fetches the thread right before acting and
  cancels if anything new arrived; checks the window and cap; stops on every stop condition in
  the plan. Messages labelled DRAFT are ignored when deciding who sent last (the fake
  reports `last_sender_is_user` as true for a trailing draft).
- **Tests:** US-63 passes; integration tests for each stop condition.
- **Depends on:** US-63, US-33 · **Estimate:** 2h

### [~] US-65 Draft creation in the thread
_Drafting through the Gmail protocol is done in the scheduler (reply headers, recipient fetched at
draft time, no-reply/self guards). Requesting `gmail.compose` and the nightly contract test wait on
US-31 and the Google projects (US-04)._

As a user, I want the draft to show up as a reply in the original Gmail thread.
- **AC:** Requests `gmail.compose` only when follow-ups are turned on; draft has `threadId`,
  `In-Reply-To`, `References`, and a "Re:" subject; the To address is fetched at that moment and
  never stored; the task is marked drafted.
- **Tests:** Unit with the fake client checks headers; contract test against the real API nightly.
- **Depends on:** US-64 · **Estimate:** 2h

### [x] US-66 Follow-up queue page
As a user, I want to see and skip upcoming follow-ups.
- **AC:** `GET /follow-ups`, `POST /follow-ups/{id}/skip`; per-application pause and custom delay;
  a page lists drafts and pending steps.
- **Tests:** Integration for skip and pause; Vitest for the page states.
- **Depends on:** US-64 · **Estimate:** 1h

### Integration check, follow-ups
- [ ] A test application on staging gets a real draft in your test Gmail on schedule.
- [ ] Replying to the thread cancels the next step.

---

## Epic 7: Daily digest (week 4)

Goal: the digest arrives on staging.

### [x] US-70 Digest content
As a user, I want a short morning summary of what changed.
- **AC:** Includes drafts waiting, new replies, rejections, interview invites, and applications
  with no reply after 7 or more days; company names and statuses only, never snippets; nothing to
  report means no email.
- **Tests:** Unit: each section; an empty day returns none; no snippet text ever appears.
- **Depends on:** US-52, US-64 · **Estimate:** 1h

### [~] US-71 Digest delivery
_`run_digest` is done (claim-once per local day, retry once, never double-send, fails closed
without a provider). Still to do: a real email provider with SPF/DKIM/DMARC (needs the domain,
US-102) and the first deploy (US-05). Scheduling is done: the digest runs in the daily cron tick (about
7-8 am Toronto time) once per local date; set `DIGEST_SEND_AFTER_LOCAL_HOUR` for the old "after 8:00" rule._

As a user, I want the digest at 8:00 in my timezone, exactly once.
- **AC:** Sent through the email provider; `digest_log` unique on user and date makes retries
  safe; failures are logged without content and retried once; local env prints to the console.
- **Tests:** Integration with a fake provider: two runs send once; timezone handling with a fake
  clock.
- **Depends on:** US-70 · **Estimate:** 1.5h

### [x] US-72 Unsubscribe
As a user, I want to turn the digest off easily.
- **AC:** Settings toggle; one-click signed unsubscribe link; `List-Unsubscribe` header.
- **Tests:** Integration: link turns digest off without a session; a tampered link is rejected.
- **Depends on:** US-71 · **Estimate:** 0.5h

### Integration check, week 4 exit
- [ ] Drafts appear in your Gmail, the digest arrives on staging, and stop-on-reply tests pass.

---

## Epic 8: Privacy and data control (week 5)

Goal: anyone can leave and take nothing of theirs left behind.

### [x] US-80 Delete my data
As a user, I want one button that removes everything about me.
- **AC:** `DELETE /me` revokes the Google token, deletes every row for the user in one
  transaction, ends the session, and sends a confirmation email.
- **Tests:** Integration: after delete, every user-owned table has zero rows for that user (the
  test enumerates tables from metadata, so new tables are covered automatically).
- **Depends on:** US-35, US-71 · **Estimate:** 1.5h
- **Notes:** Confirmation email goes through the `EmailSender` stub (no-op in production). TODO US-71:
  real sender, then make it send. TODO: replace `BACKUP_RETENTION_DAYS` in `frontend/src/constants.ts`
  with the host's real window.

### [x] US-81 Privacy page and SECURITY.md
As a friend deciding whether to connect Gmail, I want to know exactly what happens to my data.
- **AC:** Plain-language page: what is read, what is stored, what goes to the LLM, who can see
  it, how to delete, backup retention, contact; `gmail.compose` honesty note.
- **Tests:** Manual review against the plan's privacy checklist; Vitest smoke render.
- **Depends on:** US-45 decision · **Estimate:** 1h

### [x] US-82 Threat model and decision records
As a reviewer, I want to see the security thinking written down.
- **AC:** `threat-model.md` filled in; the six decision records written.
- **Tests:** Manual.
- **Depends on:** none · **Estimate:** 1h

---

## Epic 9: Hardening (week 5)

### [x] US-90 Structured logging without content
As the operator, I want logs I can debug with that never leak email content or tokens.
- **AC:** JSON logs with an allowlist of fields; subjects, snippets, and tokens are never logged.
- **Tests:** Unit: logging a record with a forbidden field drops it.
- **Depends on:** US-01 · **Estimate:** 0.5h

### [x] US-91 Security headers and CSP
As a user, I want the browser to block injected scripts.
- **AC:** Strict CSP, `X-Content-Type-Options`, `Referrer-Policy`, HSTS outside local.
- **Tests:** Integration: headers present on responses.
- **Depends on:** US-01 · **Estimate:** 0.5h

### [x] US-92 Rate limiting
As the operator, I want abuse limited on sensitive endpoints.
- **AC:** Invite code, sign-in, and sync endpoints are rate limited per IP and per user.
- **Tests:** Integration: limit exceeded returns 429.
- **Depends on:** US-12 · **Estimate:** 0.5h

---

## Epic 10: Demo mode and launch (week 5)

Goal: prod is live behind the approval step; 10 friends are invited.

### [x] US-100 Demo mode
As a recruiter on GitHub, I want to see the product without signing in.
- **AC:** `/demo` uses the same components against a static seeded dataset; no backend calls.
- **Tests:** Vitest: demo pages render with fetch stubbed to fail; Playwright demo flow.
- **Depends on:** US-53, US-54, US-66 · **Estimate:** 2h

### [~] US-101 End-to-end tests
_Done: `frontend/e2e/` (demo, accessibility with axe, mocked sign-in/CSRF, mobile) runs in the CI
`e2e` job. The staging variant (real sign-in with a test account, connect, draft appears, run after
each staging deploy, blocks promotion) waits on the first Vercel deploy (US-05) and US-04._

As the developer, I want the main flows checked after every staging deploy.
- **AC:** Playwright covers demo, sign-in, connect, dashboard, and draft appears; runs after
  each staging deploy and blocks promotion on failure.
- **Tests:** The suite.
- **Depends on:** US-05, US-100 · **Estimate:** 1.5h

### [~] US-102 Production environment
_Done in the repo: `deploy.yml` deploys `production` on tag `v*` through the GitHub Environment
`production` (required reviewers), migrating first and smoke testing after. Needs the operator:
the environment, its reviewers and secrets, production Vercel projects and domains, DNS, SPF, DKIM,
and DMARC for the email provider. Vercel has no database backups of its own: take a Neon/Supabase
backup or branch before a release (manual until automated)._

As the operator, I want prod deployed only from a tag with my approval.
- **AC:** `deploy.yml` on tag `v*`, requires GitHub environment approval, migrates, deploys API and
  frontend to the production Vercel projects, runs a smoke test; a backup or database branch is
  taken first (manual); prod domain, DNS, SPF, DKIM, and DMARC set.
- **Tests:** Manual first release; smoke step in the workflow.
- **Depends on:** US-101 · **Estimate:** 1.5h

### [~] US-103 README and launch
_README is written in the planned order with screenshots, architecture, security highlights,
badges, and roadmap. Still to do after launch: the hosted demo link, a short GIF, and inviting
the first 10 friends._

As a recruiter, I want to understand the project in two minutes.
- **AC:** README in the plan's order with demo link, GIF, screenshots, diagram, badges; first 10
  friends invited.
- **Tests:** Manual.
- **Depends on:** US-100, US-102 · **Estimate:** 1h

### Integration check, v1 definition of done
- [ ] A new invited user signs in, connects Gmail, and sees classified applications within 2
  minutes of the first sync.
- [ ] Classifier meets its targets on the eval set.
- [ ] Isolation suite proves user A cannot read or change user B's data.
- [ ] Delete my data revokes the token and wipes every row.
- [ ] Staging deploys on merge; prod deploys from a tag behind approval.
- [ ] README, architecture diagram, threat model, and demo mode are live.
- [ ] 10 friends have used it for a week with no data incident.

---

## Later (v1.1)

- US-110 Auto-send, opt in per sequence, with caps, 24-hour notice, kill switch, send log,
  bounce detection, and a staging recipient allowlist enforced in code.
- US-111 CSV export.
- US-112 Raise the user count in batches of 10 to 20.

## Cut order if behind schedule

1. US-45, US-46 (LLM fallback): rules-only still works.
2. US-62 tone presets and the per-application parts of US-66.
3. US-71, US-72 (email digest): show it in the app instead.
4. Polish in US-100.

**Never cut:** US-20, US-60, US-80, US-81.
