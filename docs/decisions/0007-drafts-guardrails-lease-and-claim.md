# 0007: Draft guardrails use a per-user lease plus a per-task claim

Status: accepted (implemented in `backend/app/services/scheduler.py`)

## Context

The scheduler runs every 15 minutes and may overlap with itself or a second worker. A duplicate
follow-up draft in a recruiter thread is the visible failure we most want to avoid. Calls to Gmail
are not transactional with the database: a worker can die after Gmail creates a draft but before
the database records it, and the worker cannot tell which side of that line it died on.

## Decision

Two layers. First, a per-user lease (`scheduler_state.lease_expires_at`) lets only one `run_due`
work on a user at a time. Second, each task is claimed (`pending` to `drafting`) and committed
before any Gmail call, then marked `drafted` after. A stale claim (older than 15 minutes) means a
worker died mid-draft. If a user draft appeared in the thread, the task is reconciled; otherwise it
is cancelled as `uncertain_draft` and the next step is rescheduled instead of retried. Failures
increment a counter up to a maximum. Messages labelled DRAFT are ignored when deciding who sent last.

## Consequences

- A crash can lose a follow-up but cannot create a second draft.
- The safe direction costs a missed follow-up in rare crash cases, which the user can see in the
  queue and recover by hand.
- Edited drafts are not detected, because a Gmail draft ID survives edits; the task is only
  reconciled once the draft is sent or deleted.
- The same claim-before-act idea is used for the digest (`digest_log`), where an uncertain send is
  also resolved by not retrying.
- The lease and claims rely on Postgres, which suits the single-database design.
