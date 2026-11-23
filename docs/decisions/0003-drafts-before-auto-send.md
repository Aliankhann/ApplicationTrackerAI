# 0003: Drafts before auto-send

Status: accepted (drafts implemented in the scheduler; real Gmail wiring pending; auto-send is
v1.1, US-110)

## Context

Follow-ups are the feature with real-world side effects: a bug could email recruiters on a user's
behalf. Google's `gmail.compose` scope allows creating drafts but can also send mail, so the scope
alone gives no protection.

## Decision

Version 1 only creates drafts in the original Gmail thread. The user reviews and sends them. The
`GmailClient` interface has no send operation, so the application code cannot send even by mistake.
The scheduler "never sends". Guardrails apply anyway: weekdays only (in `window` mode also a 9 to 11 am local window; see ADR 0009 for the daily default), a daily
draft cap, stop on any inbound reply, and a maximum number of attempts.

Auto-send is deferred to v1.1 (US-110), opt in per sequence, with a smaller cap, a 24-hour notice in
the digest, a kill switch, a send log, bounce detection, and a staging recipient allowlist enforced
in code.

## Consequences

- The privacy page can say honestly that `gmail.compose` technically allows sending and that the
  app only creates drafts, enforced in code.
- Lower risk while the guardrails are proven in real use.
- Users do one more click per follow-up.
- Edited drafts are not detected as "handled" until they are sent or deleted (see the threat model).
- The consent screen still asks for a scope broader than drafts need; there is no draft-only scope.
