---
description: Run a backlog story or feature through BA, dev, and QA with approval gates
argument-hint: <US-xx or feature description>
---
Run this workflow for: $ARGUMENTS

You are the manager. Subagents cannot call each other, so every hand-off goes through you.

1. Make sure the working tree is clean and you are on `main`, up to date with `origin/main`.
   Until staging deploys from `main` (US-05), stories commit straight to `main`. After that,
   use a feature branch and a PR per story.
2. Use the ba agent to write the spec. If it returns questions, relay them to me and wait, then
   call it again with my answers.
3. Show me the spec and wait for my approval.
4. Use the dev agent to implement the approved spec. Pass it the full spec.
5. Use the qa agent to review it. Pass it the spec and dev's report.
6. If QA says FAIL, send dev the findings, then run qa again. Stop after 3 dev and QA rounds and
   escalate to me with the open findings.
7. Before finishing, run all checks yourself and check every acceptance criterion against the
   diff. Summarize what was done, what is left, and any risks.
8. When QA passes and your own checks are green, make one commit for the story with a
   Conventional Commit title that includes the story ID, mark the story `[x]` in
   `docs/backlog.md`, and push to `main`. Then confirm CI on `main` passes; fix forward if not.
