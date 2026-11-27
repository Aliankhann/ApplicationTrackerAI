"""End-to-end pipeline eval: `uv run python -m eval.pipeline [--split tune|holdout] [--show-cases]`.

Loads a synthetic corpus (`eval/pipeline_corpus`) into FakeGmailClient (message bodies included),
runs the real `run_sync` (prefilter, classifier, extraction, applications) inside a transaction
that is rolled back, and prints a funnel, the targets, and every miss with the stage and reason it
was lost at. Output contains only case ids and synthetic corpus values; never real mail.

`tune` is for developing rules; never read the misses of `holdout` to decide what to change.

Truth: a case's company, role and status are what a user would want. Threads of one real
application (an explicit `group`, else the same company and role) must end on one card whose
status is the furthest of theirs (rejected beats everything).
"""

import argparse
import sys
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Application, Classification, User
from app.providers.classifier.rules import RulesProvider
from app.providers.gmail import MessageMeta
from app.providers.gmail.fake import FakeGmailClient
from app.repositories import applications as applications_repo
from app.repositories import threads as threads_repo
from app.services.applications import STATUS_ORDER
from app.services.classification import ApplicationStatus
from app.services.sync import SyncResult, run_sync
from eval.pipeline_corpus import SPLITS, load_split
from eval.pipeline_corpus.bodies import body_of
from eval.pipeline_corpus.model import Case, Msg

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
OWNER = "sam.student@mail.example"
STAGES = ("prefilter", "classifier", "review", "status", "company", "role")
# Targets on the holdout corpus: (name, comparison, bound).
TARGETS = (
    ("cards created for real applications", ">=", 0.95),
    ("correct status (of created)", ">=", 0.95),
    ("company correct (of created)", ">=", 0.90),
    ("role correct (of created with a role)", ">=", 0.85),
    ("rejection precision", ">=", 0.95),
    ("noise cards (not needs-review)", "<=", 2),
    ("needs-review cards from real applications (share)", "<=", 0.05),
    ("duplicate cards", "<=", 1),
)


@dataclass
class Outcome:
    case: Case
    kept: bool = False
    decisive: bool = False  # some message of the thread got a decisive classification
    application: Application | None = None
    expected_status: str | None = None
    lost_at: str | None = None  # first stage that failed (application cases only)
    reason: str = ""
    company_ok: bool | None = None
    role_ok: bool | None = None
    status_ok: bool | None = None
    owns_card: bool = False  # this thread created the card (others only joined it)

    @property
    def review(self) -> bool:
        return self.application is not None and bool(getattr(self.application, "needs_review", 0))

    @property
    def card(self) -> Application | None:
        """The decided (not needs-review) card."""
        return None if self.review else self.application


@dataclass
class PipelineReport:
    split: str
    sync: SyncResult
    outcomes: list[Outcome]
    extra_cards: dict[str, int] = field(default_factory=dict)  # application -> cards beyond one
    multi_thread: int = 0  # real applications spread over several threads
    wrong_merges: int = 0  # cards holding threads that cannot be one application
    rejection_cards: tuple[int, int] = (0, 0)  # (truly rejected, all rejected cards)


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
    client = FakeGmailClient(OWNER, threads, now=NOW)
    for c in cases:
        for i, msg in enumerate(c.messages):
            client.set_body(f"{c.id}-{i}", body_of(c, msg))
    return client


def _norm(value: str | None) -> str:
    return (value or "").casefold().strip()


def truth_key(case: Case) -> str | None:
    """Cases of one real application: an explicit group, else the same company and role."""
    if case.group:
        return case.group
    if case.kind == "application" and case.company and case.role:
        return f"{_norm(case.company)}|{_norm(case.role)}"
    return None


def _furthest(statuses: list[str]) -> str | None:
    """Rejected beats everything (it is terminal); else the furthest status along the board."""
    if "rejected" in statuses:
        return "rejected"
    ranked = [ApplicationStatus(s) for s in statuses]
    return str(max(ranked, key=STATUS_ORDER.index)) if ranked else None


def truth_statuses(cases: Sequence[Case]) -> dict[str, str | None]:
    """The status each case's card should have: a lone case its own; the threads of one
    application the furthest of theirs (order does not matter)."""
    groups: dict[str, list[Case]] = {}
    for c in cases:
        key = truth_key(c)
        if key and c.kind == "application":
            groups.setdefault(key, []).append(c)
    expected: dict[str, str | None] = {c.id: c.status for c in cases}
    for members in groups.values():
        final = _furthest([c.status for c in members if c.status])
        for c in members:
            expected[c.id] = final
    return expected


def _decisive(session: Session, thread_id: uuid.UUID) -> bool:
    rows = session.scalars(select(Classification).where(Classification.thread_id == thread_id))
    return any(r.label is not None and not r.needs_review for r in rows)


def _judge(out: Outcome) -> None:
    """Fill lost_at/reason for an application case: first stage that failed."""
    case, app = out.case, out.application
    if not out.kept:
        out.lost_at, out.reason = "prefilter", "dropped by the prefilter"
        return
    if app is None:
        out.lost_at, out.reason = "classifier", "no card (undecided)"
        return
    if out.review:
        suggestion = getattr(app, "suggested_label", None)
        out.lost_at, out.reason = "review", f"needs review, suggested {suggestion}"
        return
    out.status_ok = str(app.status) == out.expected_status
    out.company_ok = _norm(app.company) == _norm(case.company)
    out.role_ok = None if case.role is None else _norm(app.role) == _norm(case.role)
    if not out.status_ok:
        out.lost_at, out.reason = "status", f"got {app.status} expected {out.expected_status}"
    elif not out.company_ok:
        out.lost_at, out.reason = "company", f"got {app.company!r} expected {case.company!r}"
    elif out.role_ok is False:
        out.lost_at, out.reason = "role", f"got {app.role!r} expected {case.role!r}"


def _collect(
    session: Session, user_id: uuid.UUID, case: Case, expected: dict[str, str | None]
) -> Outcome:
    out = Outcome(case, expected_status=expected[case.id])
    thread = threads_repo.get_by_gmail_id(session, user_id, case.id)
    out.kept = thread is not None
    if thread is not None:
        out.application = applications_repo.get_for_thread(session, user_id, thread.id)
        out.owns_card = (
            out.application is not None and out.application.source_thread_id == thread.id
        )
        out.decisive = _decisive(session, thread.id)
    if case.kind == "application":
        _judge(out)
    return out


def _duplicates(outcomes: list[Outcome]) -> tuple[dict[str, int], int]:
    """Extra cards per real application spread over several threads, and how many there are."""
    cards: dict[str, set[uuid.UUID]] = {}
    threads: Counter[str] = Counter()
    for o in outcomes:
        key = truth_key(o.case)
        if key is None:
            continue
        threads[key] += 1
        if o.card:
            cards.setdefault(key, set()).add(o.card.id)
    multi = {k for k, n in threads.items() if n > 1}
    return {k: len(ids) - 1 for k, ids in cards.items() if len(ids) > 1 and k in multi}, len(multi)


def _conflict(a: Case, b: Case) -> bool:
    """Two cases that cannot be one application: other companies, or two different roles."""
    if _norm(a.company) != _norm(b.company):
        return True
    return bool(a.role and b.role and _norm(a.role) != _norm(b.role))


def _wrong_merging_cards(outcomes: list[Outcome]) -> list[list[Outcome]]:
    cards: dict[uuid.UUID, list[Outcome]] = {}
    for o in outcomes:
        if o.card:
            cards.setdefault(o.card.id, []).append(o)
    return [
        group
        for group in cards.values()
        if any(_conflict(a.case, b.case) for a in group for b in group)
    ]


def _merged_cases(outcomes: list[Outcome]) -> list[tuple[str, list[str]]]:
    return [
        (f"{g[0].card.company!r}/{g[0].card.role!r}" if g[0].card else "", [o.case.id for o in g])
        for g in _wrong_merging_cards(outcomes)
    ]


def _rejection_cards(outcomes: list[Outcome]) -> tuple[int, int]:
    cards: dict[uuid.UUID, bool] = {}
    for o in outcomes:
        if o.card and str(o.card.status) == "rejected":
            cards[o.card.id] = cards.get(o.card.id, False) or o.expected_status == "rejected"
    return sum(cards.values()), len(cards)


def run_pipeline(session: Session, split: str = "tune") -> PipelineReport:
    cases = load_split(split)
    user = User(google_sub=uuid.uuid4().hex, email="eval@example.test")
    session.add(user)
    session.flush()
    result = run_sync(
        session, user.id, build_client(cases), RulesProvider(), NOW, commit=session.flush
    )
    if not isinstance(result, SyncResult):
        raise RuntimeError("pipeline eval sync did not complete")
    expected = truth_statuses(cases)
    outcomes = [_collect(session, user.id, c, expected) for c in cases]
    extra, multi = _duplicates(outcomes)
    return PipelineReport(
        split,
        result,
        outcomes,
        extra,
        multi,
        len(_wrong_merging_cards(outcomes)),
        _rejection_cards(outcomes),
    )


def _pct(n: int, d: int) -> str:
    return f"{n:>3}/{d:<3} {100 * n / d:5.1f}%" if d else f"{n:>3}/0"


def _ratio(n: int, d: int) -> float:
    return n / d if d else 1.0


@dataclass(frozen=True)
class Numbers:
    apps: int
    created: int
    review: int
    status_ok: int
    company_ok: int
    with_role: int
    role_ok: int
    correct: int
    noise_cards: int
    noise_review: int
    duplicates: int


def numbers(report: PipelineReport) -> Numbers:
    apps = [o for o in report.outcomes if o.case.kind == "application"]
    others = [o for o in report.outcomes if o.case.kind != "application"]
    created = [o for o in apps if o.card]
    with_role = [o for o in created if o.case.role is not None]
    return Numbers(
        len(apps),
        len(created),
        sum(1 for o in apps if o.review),
        sum(1 for o in created if o.status_ok),
        sum(1 for o in created if o.company_ok),
        len(with_role),
        sum(1 for o in with_role if o.role_ok),
        sum(1 for o in apps if o.lost_at is None),
        sum(1 for o in others if o.card and o.owns_card),
        sum(1 for o in others if o.review and o.owns_card),
        sum(report.extra_cards.values()) + report.wrong_merges,
    )


def _target_values(report: PipelineReport, n: Numbers) -> list[float]:
    good, rejected = report.rejection_cards
    return [
        _ratio(n.created, n.apps),
        _ratio(n.status_ok, n.created),
        _ratio(n.company_ok, n.created),
        _ratio(n.role_ok, n.with_role),
        _ratio(good, rejected),
        float(n.noise_cards),
        n.review / n.apps if n.apps else 0.0,
        float(n.duplicates),
    ]


def _targets(report: PipelineReport, n: Numbers) -> list[str]:
    lines = []
    for (name, op, bound), value in zip(TARGETS, _target_values(report, n), strict=True):
        met = value >= bound if op == ">=" else value <= bound
        shown = f"{value:.3f}" if isinstance(bound, float) else f"{value:.0f}"
        lines.append(f"  {'MET ' if met else 'MISS'} {name:<52}{shown:>7}  (target {op} {bound})")
    return lines


def render_report(report: PipelineReport, show_cases: bool = False) -> str:
    outs = report.outcomes
    apps = [o for o in outs if o.case.kind == "application"]
    recs = [o for o in outs if o.case.kind == "recruiter"]
    noise = [o for o in outs if o.case.kind == "noise"]
    n = numbers(report)
    good, rejected = report.rejection_cards
    others = len(noise) + len(recs)
    rows = [
        ("application threads (truth)", f"{len(apps):>3}"),
        ("kept by prefilter", _pct(sum(1 for o in apps if o.kept), len(apps))),
        ("decisive classification", _pct(sum(1 for o in apps if o.decisive), len(apps))),
        ("card created (decided status)", _pct(n.created, n.apps)),
        ("needs-review card instead", _pct(n.review, n.apps)),
        ("correct status (of created)", _pct(n.status_ok, n.created)),
        ("company correct (of created)", _pct(n.company_ok, n.created)),
        ("role correct (of created with a role)", _pct(n.role_ok, n.with_role)),
        ("fully correct end to end", _pct(n.correct, n.apps)),
        (
            "duplicate cards",
            f"{sum(report.extra_cards.values())} extra across {len(report.extra_cards)} of "
            f"{report.multi_thread} multi-thread applications, {report.wrong_merges} wrong merges",
        ),
        ("rejection precision (cards)", _pct(good, rejected)),
        ("noise+recruiter threads with a card", f"{n.noise_cards}/{others}"),
        ("noise+recruiter threads needs-review", f"{n.noise_review}/{others}"),
    ]
    lines = [
        f"split: {report.split}   corpus: {len(outs)} threads = {len(apps)} application, "
        f"{len(recs)} recruiter, {len(noise)} noise; sync saw {report.sync.threads_seen}, "
        f"kept {report.sync.threads_kept}",
        "",
        "FUNNEL (application threads)",
        *(f"  {name:<44}{value}" for name, value in rows),
        "",
        "TARGETS (holdout)",
        *_targets(report, n),
        "",
        "LOST AT (first failing stage)",
    ]
    lost = Counter(o.lost_at for o in apps if o.lost_at)
    lines += [f"  {stage:<12}{lost[stage]}" for stage in STAGES if lost[stage]]
    lines += ["", "MISSES (case id | stage | reason)"]
    lines += [f"  {o.case.id:<24}{o.lost_at:<11}{o.reason}" for o in apps if o.lost_at]
    lines += ["", "WRONG MERGES (card | cases that cannot be one application)"]
    lines += [f"  {card}: {', '.join(ids)}" for card, ids in _merged_cases(outs)]
    lines += ["", "CARDS FOR NOISE/RECRUITER THREADS (case id | status | needs review)"]
    lines += [
        f"  {o.case.id:<24}{o.application.status:<20}{o.review}"
        for o in noise + recs
        if o.application and o.owns_card
    ]
    if show_cases:
        lines += ["", "ALL CASES (id | family | kind | kept | card)"]
        lines += [_case_row(o) for o in outs]
    return "\n".join(lines)


def _case_row(o: Outcome) -> str:
    app = o.application
    mark = " (review)" if o.review else ""
    card = f"{app.status}{mark} {app.company!r} {app.role!r}" if app else "-"
    keep = "keep" if o.kept else "drop"
    c = o.case
    return f"  {c.id:<24}{c.family:<18}{c.kind:<12}{keep:<5}{card}"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="eval.pipeline", description="End-to-end pipeline eval.")
    p.add_argument("--split", choices=SPLITS, default="tune")
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
        print(render_report(run_pipeline(session, args.split), args.show_cases))
    finally:
        session.close()
        outer.rollback()
        connection.close()
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
