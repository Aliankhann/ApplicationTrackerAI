# Pipeline diagnosis: why real job emails do not become applications

Method: 120 synthetic threads (`backend/eval/pipeline_corpus/`) modelled on common ATS, board and
company templates are loaded into `FakeGmailClient` and run through the real `run_sync` (prefilter,
rules classifier, extraction, applications) with `uv run python -m eval.pipeline [--show-cases]`.
Expectations in the corpus are what a user would want, not what the code does. No product code was
changed.

Caveats: I wrote the corpus, so the numbers are indicative, not a measurement of the real inbox.
Snippet lengths and boilerplate are my model of Gmail previews. The "what-if" experiments below
(extra rules, ATS display-name change) were run in a scratch script by patching rules in memory;
they are overfit to this corpus by construction and only show where the ceiling is.

## Confirmed pipeline behaviour

- Per thread, `sync._chosen_message` picks the latest non-draft message not from the user (first
  message if all are from the user). From it only `from_address`, `from_name`, `subject` and
  `snippet[:200]` are used. Earlier messages of the thread are never classified.
- Prefilter keeps ATS domains, then job keywords in subject/snippet/display name, then job-ish
  sender words. The rules classifier sees only domain, subject and snippet (not the display name).
- `apply_result` returns no status for `needs_review`, undecided, `irrelevant` and
  `recruiter_message`, so no application exists for them. One application per thread
  (`source_thread_id` is unique); nothing merges threads.

## Funnel (85 application threads; plus 6 recruiter and 29 noise threads)

| Stage | Count | Of |
|---|---|---|
| Application threads (truth) | 85 | |
| Kept by prefilter | 84 | 98.8% |
| Decisive label (rules, above threshold) | 59 | 69.4% |
| Application created | 58 | 68.2% |
| Correct status (of created) | 58 | 100% |
| Company found and correct (of created) | 42/58 | 72.4% |
| Role found and correct (of created with a role) | 28/51 | 54.9% |
| Fully correct end to end (status, company, role) | 25 | 29.4% |
| Duplicate cards | 6 extra cards across 2 of 3 multi-thread applications | |

Lost at (first failing stage): prefilter 1, classifier 25, apply 1, company 16, role 17.
Noise: 15/29 noise threads pass the prefilter (by design, it is biased to keep); 1/29 creates a
card (false positive). Recruiter threads: 0/6 create a card (by design).

Takeaway: when a card is created its status is right (precision is good), but only about one in
three real threads ends up as a fully correct card. Recall of the classifier and extraction quality
are the problem, not the prefilter.

## Top causes, ranked

1. **Classifier "undecided (no rule)": 24 misses (28% of application threads).** By expected
   label: confirmation 11, interview 9, rejection 3, offer 1, OA 1. By template:
   - Board confirmations with no "thank you for applying" wording: LinkedIn "Your application was
     sent to X" (li-apply-1/2/3, sp-li-contoso), Indeed "Application submitted" (in-apply-1),
     Handshake "you've successfully applied" (hs-apply-1), direct "Your application has been
     submitted" / "This is an automatic confirmation" (dir-conf-2/3).
   - "Thanks for applying" (not "Thank you for applying"): lv-conf-1;
     `conf.thank_you_applying` only matches "thank you".
   - Interview phrasing without "schedule an interview": "pick a time", "share your availability for
     a call next week", "love to chat", "move you to the next round" (dir-int-3 is only a weak
     `int.next_round` 0.6), "Interview Confirmation", calendar invites (cal-1/2), "selected to move
     forward" (ab-int-1, dir-int-1/2, gh-int-2, mt-schedule-backforth).
   - Offer: "would like to offer you the X position" (dir-off-1; `off.*` need "pleased to offer
     you" or "offer letter").
   - Rejections: "chosen to proceed with applicants whose..." (gh-rej-5), "not able to offer you the
     Avionics Software Intern position" (jv-rej-1; `rej.unable_to_offer` allows no words between
     "the" and "position").
   - Message boilerplate pushes the phrase out of the snippet window (gh-rej-2, gh-conf-6).
2. **Role extraction: 17 wrong or missing.** Typical: "interest in the Security Intern role at X",
   "for the X role" (snippets with "the <Title> role/position" fail unless the subject has it),
   "Job title: X" / "Job: X" (dir-conf-4, wd-conf-3), "offer you the X position at Northwind"
   (ab-off-1). Wrong values: "interest in the Cloud Support Intern" (sp-fabrikam-conf), "Cloud
   Engineer Intern opening and" (ic-conf-1), "Game Developer Intern job" (sr-conf-1), "Hooli Backend
   Intern" from subject "Offer - Hooli Backend Intern" (mt-draft-last).
3. **Company extraction: 16 wrong or missing.**
   - 13 of 16 are ATS senders whose display name is the company, e.g. "Pied Piper", "Stark Dynamics",
     "Massive Dynamic", "Tailspin Toys" (gh-off-1/2, gh-rej-3, lv-int-1, sr-int-1, wk-rej-1...).
     `_display_company` runs `_looks_like_person` (2-3 capitalised tokens, no org word) and rejects
     them as people unless the domain agrees, which it never does for greenhouse/lever/ashby. Only
     names with an org word ("Systems") or one word ("Hooli") survive.
   - Sentence-boundary bug: "position at Fabrikam. After careful review" gives company
     "Fabrikam. After careful review" (wd-rej-1), "Hooli. We" (gh-conf-5), "Adventure Works and"
     (wd-rej-2). Garbage text becomes the card title.
   - Assessment vendors (HackerRank, CodeSignal, HireVue) are vendors, so the company must come from
     "Acme has invited you" and currently never does (oa-hr-1, oa-cs-1, oa-hirevue-1).
   - Wrong, not just missing: calendar invites give "Google" and "Zoom" (cal-1, cal-2), and
     "Acme Corp" for "Acme" from the domain (dir-int-1), which breaks matching with other threads.
4. **Latest-message-only classification: 3 threads** differ when every message is classified
   (mt-schedule-backforth, mt-sched-ack-last, mt-int-then-wait). When the last message from the
   recruiter is "Sounds good, I'll send an invite" or a reminder, the thread is undecided, although
   an earlier message was an interview request. (Incremental sync would have kept an earlier
   decision; an initial sync, history expiry or a first sync after the thread has grown loses it.)
5. **Prefilter: 1 false drop.** cal-3, a Calendly confirmation ("Confirmed: 30 Minute Chat with ...")
   has no job keyword. Noise passing the prefilter (15/29) is not a problem by itself because
   classification catches almost all of it.
6. **Wrong classification: 2.** in-apply-2: `irr.job_alert_digest` fires on the footer text "Manage
   your Indeed job alerts" in a real confirmation, and being the first rule it wins, so the
   confirmation is labelled irrelevant. n-news-4: a newsletter mentioning "a new coding challenge
   platform" becomes an online-assessment card for company "Hacker".

## Answers to the questions

**(a) Should needs_review / undecided job threads still create a card?** Today they vanish. In the
corpus 25 real application threads (29% of all) fall in this pool and 11 noise threads
(newsletters, school mail, LinkedIn notices) would come with them, so the pool is 69% real. Split by
prefilter reason: ATS-domain pool = 8 real, 0 noise (100%); keyword pool = 17 real, 11 noise (61%).
If defaulted to status "applied" only about 11 of the 25 would sit in the right column
(confirmations); the rest are interviews/rejections/offers, so a default status is misleading.
Recommendation: show them in a "Needs review" column (or a flag) with the suggested label if any;
auto-create for ATS-domain senders, put keyword-only ones in the same column but collapsed/dismissible.
Expected funnel: created 58 -> 83 of 85 (98%), at the cost of about 11 dismissals per 120 threads.
Do not default to `applied`.

**(b) Does the 200-char window lose the key sentence?** Partly. 73 of 85 snippets start with a
greeting or boilerplate ("Hi Sam,", "[image: ...]", "View this email in your browser", "Hello, Thank
you for your interest in"). Of the 55 decisions made from the snippet, the matching phrase ends at a
median of 105 chars and 8 end at 150 or later, i.e. close to the edge. Only 3 corpus cases were written with the key
sentence after the window (gh-rej-2, gh-conf-4, gh-conf-6) and all 3 become decisive with the tail,
but the other 22 classifier misses have the phrase inside the window, so most misses are missing
rules, not truncation (the real rate on the user's inbox is unknown). Gmail's snippet is
fixed by Gmail, so "read more" means fetching the body with `format=full`, which contradicts the
metadata-only privacy design (full bodies would pass through our process even if not stored). I do
not recommend it now. First fix rules and extraction, and measure the real window loss with a
count-only probe on staging (how many kept threads end undecided while the snippet is shorter than
about 150 characters vs. 190 or more), logging counts only.

**(c) Prefilter false drops.** 1 of 85 (cal-3, scheduling tool with no keyword). The ATS list
omits `myworkday.com`: `is_ats_domain("myworkday.com")` is false (neither equal to `workday.com`
nor a subdomain), so Workday mail relies on keywords and loses tenant-based company extraction.
Add `myworkday.com` (and `wd*.myworkdayjobs.com` is already covered). Scheduling senders
(calendly.com, zoom.us, google calendar notifications) could be kept as a weak signal; they would
add undecided noise, so only with the needs-review column from (a).

**(d) Missing rules by family** (confirmed by a scratch experiment adding 7 rules for the phrases in
cause 1): created 58 -> 77, correct status 77/77, extra noise cards 0 in this corpus, still 1 (the
newsletter). Families: LinkedIn/Indeed/Handshake confirmations ("application was sent",
"application submitted", "successfully applied"), "thanks for applying", pick-a-time / share
availability / "love to chat" / "Interview Confirmation|Invitation|Request" / calendar
"Invitation: ... Interview", "would like to offer you", "not able to offer you the", "chosen to
proceed with applicants", "application was not successful" (Workday). Footer text must not trigger
`irr.job_alert_digest`: scope it to subject or require digest wording ("N new jobs"). Must be tuned
on the tune split and checked on holdout so rejection precision stays >= 0.95; I only demonstrated
the ceiling.

**(e) Extraction gaps by template.** ATS display names that look like person names (13 company
misses); the "Company. Next sentence" boundary; role from "the X role/position at Y" and "Job
title:/Job:" lines; vendor senders (HackerRank, CodeSignal, HireVue, Zoom, Google Calendar) need
"X has invited you" / "interview with X" patterns and must never yield the vendor as company;
strip "Corp/Inc/Labs" style suffixes only for matching (not display). Scratch experiment: skipping
the person guard when the sender is an ATS domain, together with (d) and `myworkday.com`, moves
fully correct cards from 25 to 34 of 85 (company misses 26 -> 17); the rest need the boundary fix and
role patterns.

**(f) Duplicates.** One real application can appear as several cards: Acme SWE gives 3 cards
(confirmation+interview in a Greenhouse thread, a direct interview with company "Acme Corp" and role
None, an assessment card with no company), Fabrikam gives 3 (confirmation, OA, interview),
Contoso and LinkedIn+ATS confirmations give 2 after (d). Rejected cards also sit next to the
live card from the earlier thread. Proposed merge key, applied when creating or advancing an
application, per user: `normalize(company)` (casefold, strip punctuation and suffixes such as
corp/inc/llc/labs) + `normalize(role)` (casefold, strip season/year and "intern(ship)" variants) +
created within about 45 days of an existing card. Rules: merge when company matches and role either
matches or one side is missing; when a card has no company, match on role plus sender domain or
thread time window only if exactly one candidate exists; never merge across different roles. Store
the extra threads on the card (needs a link table) and keep status forward-only. Roughly halves
duplicate cards here, but only works once extraction is reliable (company present, "Acme Corp" =
"Acme"), so do extraction first.

**(g) Bugs found.**
1. Only the latest non-user message is classified, so an acknowledgement or reminder hides an earlier
   decisive message (3 cases). Fix: classify every new message once and apply forward-only, or fall
   back to the latest decisive message in the thread.
2. `irr.job_alert_digest` matches footer text and outranks real confirmations (in-apply-2).
3. Company extraction returns text past the sentence end ("Fabrikam. After careful review").
4. Role extraction returns prefixes/suffixes ("interest in the ...", "... opening and", "... job").
5. Company "Google"/"Zoom" for calendar invites (vendor list lacks them).
6. `myworkday.com` is not treated as an ATS domain.
7. ATS display names with two capitalised words are rejected as person names.

None were fixed here (each touches tuned classifier or extraction behaviour with a holdout set), so
all are recommendations.

## Recommendations and expected impact (on this corpus)

| # | Change | Expected effect |
|---|---|---|
| 1 | "Needs review" column for undecided/needs_review job threads (a) | created 58 -> 83/85; about 11 extra dismissals |
| 2 | Add rules for the families in (d), fix the footer misfire (g2) | created 58 -> about 77; status stays correct |
| 3 | ATS display name without person guard; `myworkday.com` as ATS; vendor-invite company patterns | fully correct 25 -> about 34 |
| 4 | Sentence-boundary and role pattern fixes in extraction | up to 12 of the remaining company/role misses |
| 5 | Classify every message / keep the best status per thread (g1) | 3 threads |
| 6 | Merge key (f) after 3 and 4 | duplicate cards 6 -> about 2 |
| 7 | Count-only staging probe for snippet window loss; body fetch only if it proves large (b) | decision data, no privacy change |

Regression check: the existing classifier eval (`uv run python -m eval.run`) is unchanged
(tune accuracy 0.662, holdout 0.493, rejection precision 1.000 on both) and the full backend suite
passes. Note that the holdout coverage (0.49) is consistent with the 28% undecided rate here.
