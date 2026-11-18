# 0008: Classifier favours precision over recall, measured on a held-out set

Status: accepted (rules and eval gate implemented; LLM fallback not built, US-45)

## Context

A wrong "rejection" is the costliest error: it can mark a live application as dead and cancel its
follow-ups. A missed rejection only leaves an application in an older status or in "needs review".
Rules written to catch more wording will also eventually catch wrong wording.

## Decision

Rules are designed so that doubt never becomes a rejection: conditional phrasing, contrast, and
quoting demote a match to "needs review". Results below
the confidence threshold (default 0.7) never change a status. The gate in CI enforces rejection
precision of at least 0.95 and no regression in accuracy or rejection recall against
`backend/eval/baseline.json`. Synthetic fixtures are split into `tune.jsonl` (used to write rules)
and `holdout.jsonl` (measurement only, never tuned on). Real labelled email stays outside the repo.

## Consequences

- Today, on the holdout set, rejection precision is 1.0 but recall is 0.44 and accuracy 0.49;
  unseen rejection wording goes to review instead of being mislabelled. Accuracy is reported but not
  gated, because the LLM fallback is meant to raise it.
- The holdout was partly seen during QA, so its numbers are slightly optimistic; it should be
  refreshed periodically.
- Users see more "needs review" than a recall-first design would show.
- Any future LLM output goes through the same threshold and eval, so it cannot bypass the
  precision floor.
