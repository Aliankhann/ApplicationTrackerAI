# 0006: Invite-only access

Status: accepted (invite code generation implemented; the sign-in gate is US-12, not built)

## Context

Google limits an unverified app to 100 users over its lifetime, so open signup could burn the cap
within a day and cannot be undone. The people using the app hand it access to their inbox, so the
operator also wants to know who they are.

## Decision

Access needs two things: a Google test-user allowlist entry (planned, US-04) and a single-use invite
code, with returning users skipping the code. Codes are created by a CLI (`invite create`), carry
160 bits of randomness, expire, and are stored only as a SHA-256 hash, so a database leak does not
reveal usable codes. The gate rejects invalid, used, or expired codes before any user or token row
is written (US-12), and the code endpoint is rate limited (US-92). `max_users` in settings mirrors
the cap.

## Consequences

- The operator controls every slot, and invitations can be traced to a person.
- Friends need a code and an allowlist addition before they can try the app, which adds friction.
- Code generation and hashing exist today; the gate, sign-in, and rate limiting do not, so the app
  cannot yet admit anyone.
- Raising the user count later (US-112) means batches of invitations and, eventually, Google
  verification.
- A lost code cannot be recovered, only reissued.
