# 0004: Two Google Cloud projects

Status: accepted (planned; not set up yet, US-04)

## Context

Google caps an unverified production OAuth app at 100 users for the app's lifetime, and the count
never resets. In Testing mode, refresh tokens expire after 7 days but only listed test users can
sign in. Developing and testing against the production project would spend real slots on test
accounts and risk the cap.

## Decision

Use two separate projects. `tracker-staging` stays in Testing with only the developer's own test
Google accounts and allows a localhost redirect. `tracker-prod` is published as an unverified app
for up to 100 real users, with a tight test-user allowlist as well as invite codes. Each has its
own OAuth client, consent screen, and redirect URIs, and each environment has its own encryption
key and secrets.

## Consequences

- Staging experiments can never consume a production slot.
- Credentials and tokens never cross environments, which limits the blast radius of a leak.
- Users of production must click through the "Google hasn't verified this app" warning; a short
  guide is planned.
- Two sets of console configuration to keep in sync, and two consent screens that must both match
  the privacy page.
- Verification by Google would lift the cap but is out of scope for v1.
- Scope and policy details (including Limited Use) must be re-checked in the console before launch,
  since Google changes them.
