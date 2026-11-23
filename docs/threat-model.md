# Threat model

Status as of 2026-11-18. Every "Implemented" entry points at code that exists today; everything
else is labelled "Planned" with its backlog ID ([backlog.md](backlog.md)). The starting table came
from [build-plan.md](build-plan.md#security-and-privacy). This is a design document, not a legal
opinion and not legal advice; look at Canadian privacy basics (PIPEDA) before inviting people.

Important current-state facts: Google sign-in (US-11), the invite gate (US-12), connecting Gmail
(US-31), the real Google client and revoker, the LLM fallback (US-45), rate limiting (US-92), and
the real email provider (US-71) are **not built yet**. The sync, scheduler, and digest services
exist and are tested against fakes behind interfaces.

## Assets

| Asset | Why it matters | Where it lives |
| --- | --- | --- |
| Gmail refresh tokens | Read access (and, with `gmail.compose`, draft and technically send access) to a person's inbox | `oauth_tokens`, AES-GCM encrypted; key in environment settings, not the database |
| Token encryption key and session secret | Decrypt every token; forge CSRF and unsubscribe tokens | Environment settings (`TOKEN_ENCRYPTION_KEYS`, `SESSION_SECRET`) |
| Email metadata | Subjects, sender domains, 200-character snippets of job email | `email_threads`, `classifications` |
| Application records | Company, role, status history, follow-up plans | `applications`, `status_events`, `sequences`, `follow_up_tasks` |
| Account identity | Google ID, email address, timezone | `users` |
| Sessions | Act as a signed-in user | `sessions` (SHA-256 of the cookie token only) |
| The 100-user Google cap | Lifetime limit for the unverified app | Invite codes (`invite_codes`, hashes only) and the Google test-user allowlist (planned, US-04) |
| The operator's reputation and the sender domain | Spam or bulk-send incidents | Gmail drafts only in v1; digest through the email provider (planned) |

Never stored: full bodies, recipient addresses, rendered draft text
([models.py](../backend/app/models.py), [sync.py](../backend/app/services/sync.py)).

## Trust boundaries

| Boundary | What crosses it | Controls today |
| --- | --- | --- |
| Browser to API | Session cookie, CSRF header, JSON | `require_csrf` for every non-safe method ([deps.py](../backend/app/api/deps.py)), CORS limited to the app origin and `OriginCheckMiddleware` ([main.py](../backend/app/main.py), [middleware.py](../backend/app/middleware.py)), `SameSite=Lax` and `HttpOnly` session cookie, `__Host-` cookie prefix outside local ([config.py](../backend/app/config.py)), strict API CSP and security headers, SPA CSP from `frontend/public/_headers` |
| API to Postgres | Queries on user-owned rows | Every such query goes through `repositories/` filtered by `user_id`; route-enumerating isolation suite ([test_isolation.py](../backend/tests/test_isolation.py)). Row-level security is **not** implemented |
| Worker and jobs to Postgres and Gmail | Sync, scheduler, digest | Per-user leases and per-task claims ([ADR 0007](decisions/0007-drafts-guardrails-lease-and-claim.md)), digest claim-before-send. The sync and scheduler have no production entry point or schedule yet (US-05); only the digest job has a `main()` ([jobs/digest.py](../backend/app/jobs/digest.py)) |
| Backend to Google | OAuth, Gmail reads, draft creation, token revocation | Behind the `GmailClient` and `TokenRevoker` interfaces ([providers/gmail](../backend/app/providers/gmail/client.py), [revoke.py](../backend/app/providers/google/revoke.py)); the real implementations land with US-31, US-04 |
| Backend to LLM vendor (planned) | Sender domain, subject, snippet | Not built (US-45). The classifier input type carries only those three fields ([types.py](../backend/app/providers/classifier/types.py)) |
| Backend to email provider (planned) | Digest and deletion confirmation, with the user's address | Behind the `EmailSender` interface; production fails closed ("not configured") until a provider is wired ([email.py](../backend/app/providers/email.py)) |
| Public internet to signed links | Digest unsubscribe | HMAC-signed, expiring token with a purpose-bound key, no session ([unsubscribe.py](../backend/app/security/unsubscribe.py)) |

## Threats and mitigations

| Threat | Implemented | Planned |
| --- | --- | --- |
| **Token theft from the database** (a dump leaks refresh tokens) | AES-256-GCM, fresh nonce per token, user ID bound as associated data, `key_version` column, keyring of old and current keys, `tokens rotate` CLI ([crypto.py](../backend/app/security/crypto.py), [cli.py](../backend/app/cli.py)). Tokens and decryption errors are never logged | Per-environment keys and host secret storage (US-05, US-102) |
| **Cross-user access (BOLA/IDOR)** | Repository layer scopes by `user_id`; isolation suite calls every ID-taking route as user B with user A's IDs and fails CI if a route is not covered ([test_isolation.py](../backend/tests/test_isolation.py), [routes.py](../backend/tests/routes.py)); `delete_account` test enumerates tables from metadata | Row-level security if the host allows it (not scheduled) |
| **CSRF** | Double-submit plus server-derived token, header and cookie must both match; `Origin` check; CORS allow-list; sessions revoked server side on logout ([deps.py](../backend/app/api/deps.py), [sessions.py](../backend/app/security/sessions.py), [middleware.py](../backend/app/middleware.py)). Public routes are an explicit allow-list (only `/unsubscribe`) | None |
| **XSS and unsafe rendering** | Strict API CSP; SPA CSP without inline scripts; React text rendering; a test forbids `dangerouslySetInnerHTML` ([noDangerousHtml.test.ts](../frontend/src/noDangerousHtml.test.ts)); digest HTML escapes company names and strips control characters ([digest.py](../backend/app/services/digest.py)) | Deploy check that the `__API_ORIGIN__` CSP placeholder is replaced (script exists, deploy step is US-05) |
| **Prompt injection via email** | The LLM fallback is built and OFF by default (`LLM_ENABLED=false`). Classifier output is a closed label set mapped to a status by a pure function; a low-confidence or undecided result never changes a status ([classification.py](../backend/app/services/classification.py)); adversarial rule tests ([test_classifier_adversarial.py](../backend/tests/test_classifier_adversarial.py)). The Gmail interface has no send operation | When enabled: the model has no tools; email fields are escaped, wrapped as data in tags, and the system prompt calls them untrusted ([claude.py](../backend/app/providers/classifier/claude.py)); schema-constrained output re-validated with pydantic, invalid output or a non-`end_turn` stop becomes "needs review"; rejection needs confidence >= 0.9 and interview/offer >= 0.85; LLM company/role are masked and cleaned and only fill gaps; output only sets a label and never triggers an action; called only when rules are undecided ([router.py](../backend/app/providers/classifier/router.py)); kill switch, per-user daily cap and monthly call budget ([llm_controls.py](../backend/app/services/llm_controls.py)); tests in [test_llm_classifier.py](../backend/tests/test_llm_classifier.py)
| **Secrets in the public repo** | gitleaks pre-commit hook and a full-history gitleaks job in CI; `.env.example` only; Dependabot ([.pre-commit-config.yaml](../.pre-commit-config.yaml), [security.yml](../.github/workflows/security.yml)) | Verify GitHub push protection is enabled (US-02) |
| **Log leakage** | Allowlist JSON formatter drops every other field, rejects non-conforming values, never emits exception messages or tracebacks, and replaces third-party log text ([log.py](../backend/app/log.py)); request log records route templates, not URLs; `last_error` is a stable code | None |
| **Runaway sending** | The Gmail interface can create and read drafts but has no send operation; scheduler "never sends"; daily draft cap (default 5), weekday-only drafting (a 9 to 11 am local window in `window` mode; the default `daily` mode drafts at the single daily run), stop-on-reply, max attempts, stale-claim handling ([scheduler.py](../backend/app/services/scheduler.py), [followup_policy.py](../backend/app/services/followup_policy.py)). Residual: `gmail.compose` can send if our code were changed | Auto-send guardrails, kill switch, and staging allowlist (US-110, v1.1) |
| **Invite brute force** | 160-bit random codes, only the SHA-256 stored, single use with expiry, malformed codes rejected before lookup ([invite_codes.py](../backend/app/security/invite_codes.py)) | The gate and rate limiting on the code endpoint (US-12, US-92) |
| **OAuth misuse** (open redirect, replayed code, wrong audience) | Sessions are always newly created at sign-in to avoid fixation (documented in [sessions.py](../backend/app/security/sessions.py)) | `state`, PKCE, exact redirect URIs, ID token audience and issuer checks (US-11); incremental consent (US-31) |
| **Vulnerable dependencies** | Dependabot (uv, npm, Actions), `pip-audit`, `pnpm audit --prod`, CodeQL, weekly schedule ([security.yml](../.github/workflows/security.yml)) | None |
| **Session theft or abuse** | Only a hash of the cookie token is stored; absolute (14 days) and idle (72 hours) expiry; at most 10 active sessions per user; disabled users cannot resolve a session | None |
| **Digest as a leak path** | Digest reads company names and statuses only, never subjects or snippets ([digest.py](../backend/app/services/digest.py)); one-click signed unsubscribe | SPF, DKIM, DMARC on the sending domain (US-71, US-102) |
| **Abuse and floods on the API** | Request IDs and structured logs | Per-IP and per-user rate limits (US-92) |
| **Insider (operator) access** | No code path shows email content to an operator; audit log holds actions only, with no IP, user agent, or content ([models.py](../backend/app/models.py)) | Counts-only admin view (not scheduled). The operator can still read the database directly; this is a trust assumption, stated on the privacy page |

## Residual risks

Known, documented, and accepted for now.

- **Classifier recall.** Rules favour precision. On the held-out synthetic set, accuracy is 0.49 and
  rejection recall 0.44, with rejection precision 1.0 and no wrong automatic labels
  ([baseline.json](../backend/eval/baseline.json)). Missed rejections go to "needs review". The LLM
  fallback (US-45) is meant to close the gap, which is why accuracy is not yet gated. The holdout is
  partly seen and slightly optimistic ([eval/README.md](../backend/eval/README.md)).
  See [ADR 0008](decisions/0008-classifier-precision-over-recall.md).
- **Company and role extraction.** It only sees threads the prefilter and classifier kept, and it
  cannot separate staffing agencies and job boards from employers, so those come back as the
  "company". Ambiguous two-word names are returned as unknown. The manual fix (US-51) is the remedy.
- **Edited drafts are not detected.** A Gmail draft ID survives edits, so the scheduler only notices
  a draft once it is sent or deleted ([scheduler.py](../backend/app/services/scheduler.py)).
- **Uncertain draft creation.** If a worker dies mid-draft, the task is cancelled as
  `uncertain_draft` rather than retried, so a follow-up can be lost but not duplicated.
- **Digest uncertain-send tradeoff.** A claim left in "sending" is closed with no retry, so a user
  may miss a digest but never gets two ([repositories/digest.py](../backend/app/repositories/digest.py)).
- **`gmail.compose` can send.** "Drafts only" is enforced by our code, not by Google.
- **Stored subjects.** A subject (up to 998 characters) and a snippet (200) are stored per kept
  thread, and `users.email` is stored. Prefiltering reduces but cannot eliminate non-job mail being
  kept.
- **Google unverified-app status.** Users click through a warning, and refresh tokens expire after
  7 days in the staging project's Testing mode (planned setup, US-04).
- **Real Google calls not wired.** Until US-31, disconnect returns 503 in production and account
  deletion proceeds without revoking at Google (reported as `revoked_at_google: false`). The deletion
  confirmation email is not sent in production until a provider is wired.
- **Backups.** Deleted rows persist in host backups until they age out. TODO: retention window not
  decided, and hosting provider not chosen.
- **No row-level security.** Isolation rests on the repository layer and tests.
- **Audit log retention.** `purge_audit` (365 days) has no scheduled caller yet.
- **Operator access.** A person with database and key access can read stored metadata and decrypt
  tokens. Mitigation is separation of the key from the database and a small trusted operator.

## Incident response outline

Suspected token or key leak:

1. Contain. Take the API and jobs offline if the leak is active. Revoke the compromised secret at
   its source (hosting secrets, repository, provider).
2. Rotate the encryption key. Add a new key version to `TOKEN_ENCRYPTION_KEYS`, set it current, run
   `uv run python -m app.cli tokens rotate`, check `failed=0`, then remove the old key. If the old
   key itself leaked, rotation is not enough: also revoke the tokens (next step).
3. Revoke tokens. Revoke every refresh token at Google and mark them revoked in `oauth_tokens`;
   users must reconnect. Rotate `SESSION_SECRET` to invalidate CSRF and unsubscribe tokens, and
   revoke all sessions (`sessions.revoke_all_for_user`).
4. Rotate the Google OAuth client secret and the email and LLM provider keys.
5. Assess. Use the audit log and structured request logs (they hold no content) to bound the window
   and the affected users.
6. Notify. Tell affected users promptly and plainly: what happened, what data was involved (metadata
   only, never bodies), what was done, and what they should do (remove access at Google, reconnect).
   Report to Google if required by the API terms, and consider privacy-regulator obligations.
7. Learn. Write a short post-incident note, add a regression test, and update this file.

Vulnerability reports follow [SECURITY.md](../SECURITY.md).
