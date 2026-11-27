"""End-to-end pipeline eval: both corpora run through the real sync and the report renders.

The holdout is frozen (its hash is pinned) and measurement-only; tune is what rules are written on.
"""

import hashlib

import pytest
from sqlalchemy.orm import Session

from eval.pipeline import numbers, render_report, run_pipeline, truth_statuses
from eval.pipeline_corpus import load_split
from eval.pipeline_corpus.bodies import body_of
from eval.pipeline_corpus.corpus import build_corpus
from eval.pipeline_corpus.holdout import build_holdout

HOLDOUT_SHA256 = "007e3d745c8163f90e1315a0045812863156229f792c41995d855d91ff801943"


def test_corpus_is_big_enough_and_has_unique_ids_for_every_kind() -> None:
    cases = build_corpus()
    assert len(cases) >= 100
    assert {c.kind for c in cases} == {"application", "recruiter", "noise"}
    assert len({c.id for c in cases}) == len(cases)


def test_holdout_is_frozen() -> None:
    """Never edit the holdout once rules work has started: write a fresh one instead."""
    digest = hashlib.sha256(repr(build_holdout()).encode()).hexdigest()
    assert digest == HOLDOUT_SHA256


def test_holdout_covers_the_template_families_and_is_disjoint_from_tune() -> None:
    cases = build_holdout()
    apps = [c for c in cases if c.kind == "application"]
    assert len(cases) >= 80
    distinct = {c.group or c.id for c in apps}
    assert len(distinct) >= 55
    families = {c.family for c in apps}
    assert {
        "workday", "icims", "successfactors", "taleo", "greenhouse", "lever", "ashby",
        "smartrecruiters", "workable", "linkedin", "indeed", "handshake", "direct",
        "recruiter", "calendar", "hackerrank", "codesignal", "codility", "hirevue",
    } <= families  # fmt: skip
    tune_companies = {c.company for c in build_corpus() if c.company}
    assert not tune_companies & {c.company for c in apps if c.company} - {"Vandelay Industries"}


def test_holdout_messages_carry_written_bodies_and_snippets_derive_from_them() -> None:
    for case in build_holdout():
        for msg in case.messages:
            assert msg.body and msg.snippet == " ".join(msg.body.split())[:200]


def test_tune_bodies_are_derived_from_the_snippets() -> None:
    for case in build_corpus():
        for msg in case.messages:
            assert " ".join(msg.snippet.split()) in " ".join(body_of(case, msg).split())


def test_truth_statuses_fold_threads_of_one_application() -> None:
    expected = truth_statuses(build_holdout())
    assert {expected[i] for i in ("h-g1-conf", "h-g1-int", "h-g1-rej")} == {"rejected"}
    assert {expected[i] for i in ("h-g2-conf", "h-g2-oa", "h-g2-int")} == {"interview"}
    assert all(
        expected[c.id] == c.status for c in build_holdout() if c.group and c.id.startswith("h-g")
    )


def test_pipeline_report_renders_funnel_targets_and_misses(db_session: Session) -> None:
    report = run_pipeline(db_session, "tune")
    text = render_report(report)
    for heading in ("FUNNEL", "TARGETS", "LOST AT", "MISSES", "WRONG MERGES"):
        assert heading in text
    assert report.sync.threads_seen == len(build_corpus())


def test_show_cases_lists_every_case(db_session: Session) -> None:
    text = render_report(run_pipeline(db_session, "holdout"), show_cases=True)
    assert all(c.id in text for c in load_split("holdout"))


@pytest.mark.parametrize("split", ["tune", "holdout"])
def test_rejection_precision_holds_on_both_splits(db_session: Session, split: str) -> None:
    report = run_pipeline(db_session, split)
    good, rejected = report.rejection_cards
    assert rejected > 0 and good / rejected >= 0.95


def test_tune_pipeline_numbers_do_not_regress(db_session: Session) -> None:
    n = numbers(run_pipeline(db_session, "tune"))
    assert n.created / n.apps >= 0.95
    assert n.company_ok / n.created >= 0.90
    assert n.role_ok / n.with_role >= 0.85
    assert n.noise_cards <= 2 and n.review / n.apps <= 0.05


def test_holdout_pipeline_numbers_are_measured_not_gated(db_session: Session) -> None:
    """The holdout targets are reported in docs/pipeline-diagnosis.md; only a floor is enforced
    here so a regression is noticed without tuning on it."""
    n = numbers(run_pipeline(db_session, "holdout"))
    assert (n.created + n.review) / n.apps >= 0.95  # almost nothing vanishes
    assert n.created / n.apps >= 0.85
