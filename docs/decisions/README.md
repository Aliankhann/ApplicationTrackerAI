# Decision records

One short file per decision: context, decision, consequences, and status. Status says what is built
today, because some decisions are made but not implemented yet.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-python-fastapi.md) | Python and FastAPI for the backend | Accepted, implemented |
| [0002](0002-metadata-only-storage.md) | Metadata-only storage | Accepted, implemented |
| [0003](0003-drafts-before-auto-send.md) | Drafts before auto-send | Accepted; drafts built, Gmail wiring pending |
| [0004](0004-two-google-cloud-projects.md) | Two Google Cloud projects | Accepted, not set up yet |
| [0005](0005-classifier-provider-interface.md) | Classifier provider interface | Accepted; rules built, LLM not built |
| [0006](0006-invite-only-access.md) | Invite-only access | Accepted; code generation built, gate not built |
| [0007](0007-drafts-guardrails-lease-and-claim.md) | Draft guardrails: lease plus claim | Accepted, implemented |
| [0008](0008-classifier-precision-over-recall.md) | Classifier favours precision over recall | Accepted; rules and gate built |
| [0009](0009-hosting-on-vercel.md) | Hosting everything on Vercel Hobby, one daily cron | Accepted; code and workflow built, first deploy needs the operator |
| [0010](0010-read-job-email-bodies-in-memory.md) | Read job email bodies in memory, store only derived fields | Accepted, implemented; supersedes the read side of 0002 |

Add new records with the next number. Do not rewrite an accepted record; supersede it with a new
one and update its status.

Related: [architecture](../architecture.md), [threat model](../threat-model.md).
