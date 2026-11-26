"""End-to-end pipeline eval: `uv run python -m eval.pipeline [--show-cases]`.

Loads the synthetic corpus (`eval/pipeline_corpus`) into FakeGmailClient, runs the real `run_sync`
(prefilter, rules classifier, extraction, applications) inside a transaction that is rolled back,
and prints a funnel plus every miss with the stage and reason it was lost at. Output contains only
case ids and synthetic corpus values; never real mail.
"""

import argparse
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Application, User
from app.providers.classifier.rules import RulesProvider
from app.providers.classifier.types import ClassificationInput, ClassificationResult
from app.providers.gmail import MessageMeta
from app.providers.gmail.fake import FakeGmailClient
from app.repositories import applications as applications_repo
from app.repositories import threads as threads_repo
from app.services.classification import apply_result
from app.services.prefilter import EmailMeta, prefilter, sender_domain
from app.services.sync import MAX_SNIPPET, SyncResult, _chosen_message, run_sync
from eval.pipeline_corpus.corpus import build_corpus
from eval.pipeline_corpus.model import Case, Msg

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
OWNER = "sam.student@mail.example"
STAGES = ("prefilter", "classifier", "apply", "status", "company", "role")


class _Recording:
    """Wraps the classifier and remembers each result by input, to attribute misses to rules."""

    def __init__(self, inner: RulesProvider) -> None:
        self.inner = inner
        self.seen: dict[ClassificationInput, ClassificationResult] = {}

    def classify(self, inp: ClassificationInput) -> ClassificationResult:
        result = self.inner.classify(inp)
        self.seen[inp] = result
        return result


@dataclass
class Outcome:
    case: Case
    kept: bool = False
    prefilter_reason: str = ""
    result: ClassificationResult | None = None
    application: Application | None = None
    lost_at: str | None = None  # first stage that failed (application cases only)
    reason: str = ""
    company_ok: bool | None = None
    role_ok: bool | None = None
    status_ok: bool | None = None
    tail_decisive: bool = False  # what-if: decisive if text after the snippet window were read
    folded_status: str | None = None  # what-if: all messages classified, forward-only


@dataclass
class PipelineReport:
    sync: SyncResult
    outcomes: list[Outcome]
    extra_cards: dict[str, int] = field(default_factory=dict)  # group -> cards beyond the first
    group_cards: dict[str, int] = field(default_factory=dict)


def _to_meta(case: Case, msg: Msg, index: int) -> MessageMeta:
    sent = NOW - timedelta(days=msg.days_ago) + timedelta(minutes=index)
    labels = {"DRAFT"} if msg.draft else {"SENT" if msg.from_user else "INBOX"}
    return MessageMeta(
        message_id=f"{case.id}-{index}",
        thread_id=case.id,
        from_address=msg.from_address,
        from_name=msg.from_name,
        subject=msg.subject,
        snippet=msg.snippet,
        sent_at=sent,
        from_user=msg.from_user,
        rfc822_message_id=f"<{case.id}-{index}@corpus.example>",
        label_ids=frozenset(labels),
    )


def build_client(cases: Sequence[Case]) -> FakeGmailClient:
    threads = {c.id: [_to_meta(c, msg, i) for i, msg in enumerate(c.messages)] for c in cases}
    return FakeGmailClient(OWNER, threads, now=NOW)


def _decisive(result: ClassificationResult | None) -> bool:
    return result is not None and result.label is not None and not result.needs_review


def _describe(result: ClassificationResult | None) -> str:
    if result is None:
        return "no result"
    rule = result.rule_id or "no rule"
    if result.label is None:
        return f"undecided ({rule})"
    if result.needs_review:
        return f"needs_review ({rule}, {result.label} conf {result.confidence:.2f})"
    return f"{result.label} ({rule})"


def _norm(value: str | None) -> str:
    return (value or "").casefold().strip()


def _fold_status(case: Case, provider: RulesProvider) -> str | None:
    """What-if: classify every non-draft message from others; keep the furthest status."""
    from app.services.applications import _can_move

    status = None
    for msg in case.messages:
        if msg.draft or msg.from_user:
            continue
        domain = sender_domain(msg.from_address)
        res = provider.classify(ClassificationInput(domain, msg.subject, msg.snippet[:MAX_SNIPPET]))
        new = apply_result(status, res)
        if new is not None and (status is None or _can_move(status, new)):
            status = new
    return str(status) if status else None


def _tail_decisive(case: Case, provider: RulesProvider) -> bool:
    msg = case.messages[-1]
    if not msg.tail:
        return False
    text = (
        (msg.snippet[:MAX_SNIPPET] + msg.tail)
        if len(msg.snippet) > MAX_SNIPPET
        else msg.snippet + msg.tail
    )
    return _decisive(
        provider.classify(ClassificationInput(sender_domain(msg.from_address), msg.subject, text))
    )


def _judge(out: Outcome) -> None:
    """Fill lost_at/reason for an application case: first stage that failed."""
    case, app = out.case, out.application
    if not out.kept:
        out.lost_at, out.reason = "prefilter", f"dropped ({out.prefilter_reason})"
        return
    if not _decisive(out.result):
        out.lost_at, out.reason = "classifier", _describe(out.result)
        return
    if app is None:
        out.lost_at, out.reason = "apply", f"no application for {_describe(out.result)}"
        return
    out.status_ok = str(app.status) == case.status
    out.company_ok = _norm(app.company) == _norm(case.company)
    out.role_ok = None if case.role is None else _norm(app.role) == _norm(case.role)
    if not out.status_ok:
        out.lost_at, out.reason = (
            "status",
            f"got {app.status} expected {case.status} via {_describe(out.result)}",
        )
    elif not out.company_ok:
        out.lost_at, out.reason = "company", f"got {app.company!r} expected {case.company!r}"
    elif out.role_ok is False:
        out.lost_at, out.reason = "role", f"got {app.role!r} expected {case.role!r}"


def _collect(
    session: Session, user_id: uuid.UUID, case: Case, rec: _Recording, p: RulesProvider
) -> Outcome:
    out = Outcome(case)
    thread = threads_repo.get_by_gmail_id(session, user_id, case.id)
    chosen = _chosen_message(build_client([case]).get_thread(case.id))
    if chosen is not None:
        snippet = chosen.snippet[:MAX_SNIPPET]
        decision = prefilter(
            EmailMeta(chosen.from_address, chosen.from_name, chosen.subject, snippet)
        )
        out.prefilter_reason = decision.reason
        domain = sender_domain(chosen.from_address)
        out.result = rec.seen.get(ClassificationInput(domain, chosen.subject, snippet))
    out.kept = thread is not None
    if thread is not None:
        out.application = applications_repo.get_for_thread(session, user_id, thread.id)
    out.tail_decisive = _tail_decisive(case, p)
    out.folded_status = _fold_status(case, p)
    if case.kind == "application":
        _judge(out)
    return out


def run_pipeline(session: Session) -> PipelineReport:
    cases = build_corpus()
    user = User(google_sub=uuid.uuid4().hex, email="eval@example.test")
    session.add(user)
    session.flush()
    provider = RulesProvider()
    rec = _Recording(provider)
    result = run_sync(session, user.id, build_client(cases), rec, NOW, commit=session.flush)
    if not isinstance(result, SyncResult):
        raise RuntimeError("pipeline eval sync did not complete")
    outcomes = [_collect(session, user.id, c, rec, provider) for c in cases]
    cards = Counter(o.case.group for o in outcomes if o.case.group and o.application)
    totals = Counter(o.case.group for o in outcomes if o.case.group)
    return PipelineReport(
        result,
        outcomes,
        {g: n - 1 for g, n in cards.items() if n > 1},
        dict(totals),
    )


def _pct(n: int, d: int) -> str:
    return f"{n:>3}/{d:<3} {100 * n / d:5.1f}%" if d else f"{n:>3}/0"


def _funnel(apps: list[Outcome]) -> list[str]:
    def count(pred: Callable[[Outcome], bool | None]) -> int:
        return sum(1 for o in apps if pred(o))

    created = [o for o in apps if o.application]
    with_role = [o for o in created if o.case.role is not None]
    rows = [
        ("application threads (truth)", len(apps)),
        ("kept by prefilter", count(lambda o: o.kept)),
        ("decisive label (>= threshold)", count(lambda o: _decisive(o.result))),
        ("application created", len(created)),
        ("correct status", count(lambda o: o.status_ok)),
        ("company found (of created)", sum(1 for o in created if o.company_ok)),
        ("role found (of created with a role)", sum(1 for o in with_role if o.role_ok)),
    ]
    denominators = [len(apps)] * 4 + [len(created), len(created), len(with_role)]
    return [f"  {name:<40}{_pct(n, d)}" for (name, n), d in zip(rows, denominators, strict=True)]


def _end_to_end(apps: list[Outcome]) -> int:
    return sum(1 for o in apps if o.lost_at is None)


def render_report(report: PipelineReport, show_cases: bool = False) -> str:
    outs = report.outcomes
    apps = [o for o in outs if o.case.kind == "application"]
    recs = [o for o in outs if o.case.kind == "recruiter"]
    noise = [o for o in outs if o.case.kind == "noise"]
    lines = [
        f"corpus: {len(outs)} threads = {len(apps)} application, {len(recs)} recruiter, "
        f"{len(noise)} noise; sync saw {report.sync.threads_seen}, kept {report.sync.threads_kept}",
        "",
        "FUNNEL (application threads)",
        *_funnel(apps),
        f"  {'fully correct end to end':<40}{_pct(_end_to_end(apps), len(apps))}",
        f"  {'duplicate cards (extra, beyond 1/app)':<40}"
        f"{sum(report.extra_cards.values())} extra cards across {len(report.extra_cards)} of "
        f"{len(report.group_cards)} multi-thread applications",
        "",
        "LOST AT (first failing stage)",
    ]
    lost = Counter(o.lost_at for o in apps if o.lost_at)
    lines += [f"  {stage:<12}{lost[stage]}" for stage in STAGES if lost[stage]]
    reasons = Counter(
        o.reason.split(" via ")[0] if o.lost_at in ("prefilter", "classifier") else ""
        for o in apps
        if o.lost_at
    )
    lines += ["", "TOP REASONS (prefilter / classifier misses)"]
    lines += [f"  {n:>3}  {r}" for r, n in reasons.most_common() if r]
    lines += _side_sections(recs, noise, apps)
    lines += ["", "MISSES (case id | stage | reason)"]
    lines += [f"  {o.case.id:<24}{o.lost_at:<11}{o.reason}" for o in apps if o.lost_at]
    if show_cases:
        lines += ["", "ALL CASES (id | family | kind | kept | result | app)"]
        lines += [_case_row(o) for o in outs]
    return "\n".join(lines)


def _case_row(o: Outcome) -> str:
    app = o.application
    card = f"{app.status} {app.company!r} {app.role!r}" if app else "-"
    keep = "keep" if o.kept else "drop"
    c = o.case
    return f"  {c.id:<24}{c.family:<18}{c.kind:<12}{keep:<5}{_describe(o.result):<48}{card}"


def _side_sections(recs: list[Outcome], noise: list[Outcome], apps: list[Outcome]) -> list[str]:
    pool = [o for o in apps if o.kept and not _decisive(o.result)]
    noise_pool = [o for o in noise if o.kept and not _decisive(o.result)]
    tail = [o for o in apps if o.lost_at and o.tail_decisive]
    fold = [
        o
        for o in apps
        if len(o.case.messages) > 1
        and o.folded_status != (str(o.application.status) if o.application else None)
    ]
    rows = [
        ("recruiter threads creating an application", f"{_count(recs)}/{len(recs)} (by design 0)"),
        ("noise threads kept by prefilter", f"{sum(1 for o in noise if o.kept)}/{len(noise)}"),
        ("noise threads creating an application", f"{_count(noise)}/{len(noise)}"),
        (
            "what-if undecided/needs_review get a card",
            f"+{len(pool)} real, +{len(noise_pool)} noise",
        ),
        ("what-if text after the snippet were read", f"+{len(tail)} misses become decisive"),
        ("what-if every message classified", f"{len(fold)} multi-message threads differ"),
    ]
    return ["", "SIDE METRICS", *(f"  {name:<44}{value}" for name, value in rows)]


def _count(outcomes: list[Outcome]) -> int:
    return sum(1 for o in outcomes if o.application)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="eval.pipeline", description="End-to-end pipeline eval.")
    p.add_argument("--show-cases", action="store_true", help="print one row per corpus case")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    engine = create_engine(get_settings().database_url)
    connection = engine.connect()
    outer = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        print(render_report(run_pipeline(session), args.show_cases))
    finally:
        session.close()
        outer.rollback()
        connection.close()
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
