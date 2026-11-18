# 0005: Classifier provider interface

Status: accepted (interface, rules provider, and cache implemented; LLM provider not built, US-45)

## Context

Most job emails follow predictable patterns that rules handle cheaply and deterministically, but
some do not. An LLM could cover those, at the cost of sending email text to a third party,
spending money, and being non-deterministic. The vendor may also change.

## Decision

Callers depend only on `ClassifierProvider.classify(input) -> result`. The input type carries just
the sender domain, subject, and snippet, which is the most any provider may ever see. `RulesProvider`
is implemented, and `CachingProvider` wraps any provider with an in-memory cache keyed by a hash of
the input. A Claude-based fallback is planned behind the same interface (US-45), used only when no
rule fires or rules conflict, with schema-validated output, no tools, and a per-user cap and kill
switch (US-46).

## Consequences

- Rules-only works today and is what CI evaluates; the LLM can be cut without touching callers.
- The vendor can be swapped, or removed, without a data-model change; classifications record
  `method`, `rule_id`, and `model_version`.
- No email data leaves the system today. Enabling the LLM requires a Limited Use review, vendor
  terms, and an update to the privacy page first.
- Results flagged "needs review" never change a status, so a weak provider degrades to manual work
  rather than wrong data.
- The cache is per process and lost on restart.
