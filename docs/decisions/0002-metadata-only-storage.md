# 0002: Metadata-only storage

Status: accepted (implemented); the "read only metadata" part is superseded by [0010](0010-read-job-email-bodies-in-memory.md). What is stored is unchanged.

## Context

Inboxes are sensitive, the repository is public, and a database leak is the worst realistic
incident. The product only needs to know which threads are job applications, what stage each is
at, and who the employer is. Full bodies are not needed for that, and keeping them would raise
both risk and the amount a privacy page must justify.

## Decision

Store thread-level metadata only: subject, sender domain (not the full address), a snippet capped at
200 characters (enforced by a database check constraint and in code), message times and counts, and
whether the user sent the last message. Never store bodies, recipient addresses, or rendered draft
text. Recipient addresses are fetched from Gmail at draft time and discarded. Threads the prefilter
rejects are dropped before anything is written. Logs and the digest email follow the same rule:
no subjects or snippets.

## Consequences

- A database dump exposes far less than an inbox copy would.
- Classification, extraction, and debugging work from short text, which limits accuracy (see
  [0008](0008-classifier-precision-over-recall.md)); users fix mistakes by hand.
- Re-classifying later uses the stored snippet, so improved rules can be re-run without Gmail.
- Subjects (up to 998 characters) and snippets are still personal data and are deleted on disconnect
  and on account deletion.
- Anything that needs more text, such as a smarter classifier, must fetch it transiently and must
  not persist it.
