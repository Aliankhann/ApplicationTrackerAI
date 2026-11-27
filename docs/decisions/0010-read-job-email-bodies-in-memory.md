# 0010: Read job email bodies in memory, store only derived fields

Status: accepted (implemented). Supersedes the "metadata only" reading rule of
[0002](0002-metadata-only-storage.md); the storage rule of 0002 stands.

## Context

Metadata alone (subject, a 200-character snippet) is too thin. On a synthetic corpus modelled on
real ATS, board and company templates (`docs/pipeline-diagnosis.md`) only about one in three real
application threads became a fully correct card: the deciding sentence is often past the snippet,
company names sit in sign-offs, and an acknowledgement after an interview invite hid the invite.
The product goal is that almost every real job email becomes a correct card without the user
sorting, and "if applications go missing the product is useless".

## Decision

- For threads the prefilter keeps, sync fetches the text of each new message from others (at most
  the last 5 per thread per sync) with `messages.get?format=full`: text/plain preferred, else HTML
  stripped to text, attachments never requested, at most 8000 characters. The text is cleaned
  (quoted replies, footers, signature noise removed; the sign-off kept) and bounded, read by the
  rules classifier and by extraction, and then dropped.
- The body is never stored, logged, put in an exception, or sent to the LLM. The LLM input type
  keeps carrying only domain, subject and snippet: the router strips the body before any LLM call
  and the cache key ignores it. A test asserts each of these.
- Stored derived data: label, confidence, rule id and review flag per message (a classification row
  keyed by Gmail message id, no content), company, role, status. Thread rows keep subject, sender
  domain and a snippet of at most 200 characters, as before.
- If the text cannot be fetched (not found, other Gmail errors, time budget used up) the message is
  read from its snippet alone. Rate limits and a revoked grant behave as for any Gmail call.
- Body fetches are paced by the same token bucket (5 units per message).

## Consequences

- More mail passes through the server process than before, in memory, for the length of one sync
  step. A compromised process during a sync could read it; the database still holds no bodies. The
  threat model, architecture and privacy page say so.
- Gmail scope is unchanged (`gmail.readonly` already allowed reading bodies).
- Sync costs more Gmail quota per kept thread (up to 5 message fetches); the pacing and time budget
  bound it.
- The rules gain body-aware guards (conditional wording, contrast scoped to a sentence); rejection
  precision stays gated at 0.95 on both splits.
