# Classifier eval

Synthetic labeled emails in `fixtures/`: `tune.jsonl` (used to write and adjust rules) and
`holdout.jsonl` (measurement only). Each line is `{id, from_domain, subject, snippet, label}`
with a real label (never `needs_review`).

**Holdout must never be used to tune rules.** Do not read its errors to decide what to add and
do not edit its cases after rules work starts. If it is ever contaminated, write a fresh one.

Real labeled emails stay outside the repo. Put them in a gitignored `eval-data/` directory (same
`tune.jsonl` / `holdout.jsonl` layout) and run `uv run python -m eval.run --data eval-data`.

```
uv run python -m eval.run [--split tune|holdout|all] [--data PATH] [--json] [--show-errors]
uv run python -m eval.run --write-baseline   # only after a deliberate, reviewed change
```

Output never includes subjects or snippets; `--show-errors` prints case ids only.

## Gate

`tests/test_eval_gate.py` runs the rules provider on both splits and fails if rejection
precision is below `max(0.95, baseline - 0.01)`, or accuracy or rejection recall fall more than
0.02 below `baseline.json`. Accuracy counts needs-review as wrong.

The plan's targets (accuracy >= 0.90, rejection precision >= 0.95) are reported on every run,
but rules alone do not reach 0.90 accuracy yet (most misses go to review, which the LLM fallback
is meant to resolve), so the gate enforces only the precision floor and no regression.

## Holdout freshness

Two holdout cases were inspected during QA of US-42, so holdout is partly seen and numbers
measured on it after that change are slightly optimistic. Refresh it periodically with new,
unseen synthetic cases (and rewrite the baseline once when you do).
