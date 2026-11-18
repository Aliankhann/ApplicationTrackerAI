# Security policy

This project handles access to people's inboxes, so security reports are welcome.

Please report vulnerabilities privately through GitHub's
[private vulnerability reporting](../../security/advisories/new) instead of a public issue.
I aim to acknowledge reports within 72 hours.

## Scope

In scope:

- The backend (`backend/`): authentication and sessions, CSRF protection, invite codes, token
  encryption and key handling, per-user data isolation, the sync, scheduler, and digest jobs, and
  logging.
- The frontend (`frontend/`): XSS, unsafe rendering of email-derived text, and leaks of data to
  third parties.
- Secrets or personal data committed to this repository or its history.
- Anything that could let one user read or change another user's data, send mail on a user's
  behalf, or recover a refresh token.

Out of scope:

- Findings that need a rooted device, a compromised browser, or physical access.
- Denial of service through sheer traffic volume, and automated scanner output with no
  demonstrated impact.
- Google's own services, and the hosting or email providers' platforms.
- The demo at `/demo`, which runs on synthetic data and makes no API calls.

See [docs/threat-model.md](docs/threat-model.md) for the known threats and accepted residual risks.

## What to include in a report

- A short description of the issue and its impact.
- The affected route, file, or commit, and the steps to reproduce it.
- A proof of concept using your own test account and synthetic data.
- Your suggested fix, if you have one (optional).

## Response targets

These are best-effort targets from one maintainer, not guarantees.

- Acknowledgement within 72 hours.
- An initial assessment within 7 days.
- A fix or mitigation plan within 30 days for confirmed issues, sooner for anything that exposes
  user data or tokens.
- Credit in the advisory if you want it.

## Never include real user data

Do not put real email content, real tokens, session cookies, encryption keys, or any other
person's data in a report, issue, pull request, or screenshot. If you find real data or a secret in
the repository, say where it is without pasting it. Use synthetic accounts and data for testing,
and only test against your own account.
