"""End-to-end pipeline eval: the synthetic corpus runs through the real sync and the report renders.

No thresholds yet: the numbers are tracked in docs/pipeline-diagnosis.md.
"""

from sqlalchemy.orm import Session

from eval.pipeline import render_report, run_pipeline
from eval.pipeline_corpus.corpus import build_corpus


def test_corpus_is_big_enough_and_has_unique_ids_for_every_kind() -> None:
    cases = build_corpus()
    assert len(cases) >= 100
    assert {c.kind for c in cases} == {"application", "recruiter", "noise"}
    assert len({c.id for c in cases}) == len(cases)


def test_pipeline_report_renders_funnel_and_misses(db_session: Session) -> None:
    report = run_pipeline(db_session)
    text = render_report(report)
    for heading in ("FUNNEL", "LOST AT", "SIDE METRICS", "MISSES"):
        assert heading in text
    assert report.sync.threads_seen == len(build_corpus())


def test_show_cases_lists_every_case(db_session: Session) -> None:
    text = render_report(run_pipeline(db_session), show_cases=True)
    assert all(c.id in text for c in build_corpus())
