"""US-42: eval fixtures, harness metrics, CLI privacy, and the regression gate (synthetic data)."""

import json
import re
from pathlib import Path

import pytest

from app.providers.classifier import rules
from app.providers.classifier.rules import RulesProvider
from app.providers.classifier.types import ClassificationInput, ClassificationResult, Label
from eval.run import (
    FIXTURES,
    SPLITS,
    Case,
    LabelStats,
    Report,
    evaluate,
    format_table,
    gate_failures,
    load_baseline,
    load_cases,
    main,
    run_gate,
)

LABELS = {str(label) for label in Label}


def _raw(split: str) -> list[dict[str, str]]:
    lines = (FIXTURES / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_us42_ac1_fixture_files_validate() -> None:
    rows = {split: _raw(split) for split in SPLITS}
    every = [r for split in SPLITS for r in rows[split]]
    assert len({r["id"] for r in every}) == len(every)
    assert all(set(r) == {"id", "from_domain", "subject", "snippet", "label"} for r in every)
    assert all(r["label"] in LABELS for r in every)
    assert all(len(r["snippet"]) <= 200 for r in every)
    assert len(rows["tune"]) >= 120
    assert len(rows["holdout"]) >= 60
    for split in SPLITS:
        labels = [r["label"] for r in rows[split]]
        assert set(labels) == LABELS
        assert labels.count("rejection") >= 25
    pairs = [{(r["subject"], r["snippet"]) for r in rows[split]} for split in SPLITS]
    assert not pairs[0] & pairs[1]


def _case(i: int, label: Label) -> Case:
    return Case(f"c{i}", "x.example", f"subject {i}", f"snippet {i}", label)


class _Scripted:
    """Fake provider: answers by case number from a fixed script."""

    def __init__(self, answers: dict[str, Label | None]) -> None:
        self._answers = answers

    def classify(self, inp: ClassificationInput) -> ClassificationResult:
        label = self._answers[inp.subject.split()[-1]]
        return ClassificationResult(label, 0.9, "rules", None, label is None)


def test_us42_ac2_evaluate_computes_known_metrics() -> None:
    rej, off, conf = Label.REJECTION, Label.OFFER, Label.CONFIRMATION
    cases = [_case(1, rej), _case(2, rej), _case(3, rej), _case(4, off), _case(5, conf)]
    answers: dict[str, Label | None] = {"1": rej, "2": None, "3": off, "4": rej, "5": conf}
    report = evaluate(_Scripted(answers), cases)
    assert report.n == 5
    assert report.accuracy == pytest.approx(2 / 5)  # cases 1 and 5; review counts as wrong
    assert report.coverage == pytest.approx(4 / 5)
    assert report.rejection_precision == pytest.approx(1 / 2)
    assert report.rejection_recall == pytest.approx(1 / 3)
    assert report.per_label["rejection"].support == 3
    assert report.per_label["offer"].precision == 0.0
    assert report.per_label["confirmation"].recall == 1.0
    assert report.confusion["rejection"] == {"rejection": 1, "needs_review": 1, "offer": 1}
    assert report.confusion["offer"] == {"rejection": 1}


def test_us42_ac3_cli_never_prints_subject_or_snippet(capsys: pytest.CaptureFixture[str]) -> None:
    texts = {r[k] for split in SPLITS for r in _raw(split) for k in ("snippet", "subject")}
    texts = {x for x in texts if len(x) >= 6}
    for argv in (["--show-errors"], ["--json", "--show-errors"], ["--split", "tune"]):
        assert main(argv) == 0
        out = capsys.readouterr().out
        assert "accuracy" in out
        assert not [x for x in texts if x in out]
    main(["--show-errors"])
    assert re.search(r"errors: (t|h)\d{3}", capsys.readouterr().out)


def test_us42_ac3_cli_accepts_private_data_dir(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    line = {
        "id": "p1",
        "from_domain": "a.example",
        "subject": "s",
        "snippet": "n",
        "label": "offer",
    }
    (tmp_path / "tune.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    assert main(["--data", str(tmp_path), "--split", "tune"]) == 0
    assert "n=1" in capsys.readouterr().out


def test_us42_cli_reports_bad_case_without_echoing_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = {
        "id": "p1",
        "from_domain": "a.example",
        "subject": "s",
        "snippet": "n",
        "label": "offer",
    }
    leak_text = "SECRET-SNIPPET-TEXT"
    bad = {**good, "snippet": leak_text, "label": "not_a_label"}
    (tmp_path / "tune.jsonl").write_text(
        json.dumps(good) + "\n" + json.dumps(bad) + "\n", encoding="utf-8"
    )
    assert main(["--data", str(tmp_path), "--split", "tune"]) == 2
    err = capsys.readouterr().err
    assert err.strip() == "error: tune.jsonl:2: invalid case"
    (tmp_path / "tune.jsonl").write_text("{not json\n", encoding="utf-8")
    assert main(["--data", str(tmp_path), "--split", "tune"]) == 2
    assert main(["--data", str(tmp_path / "missing"), "--split", "tune"]) == 2
    assert leak_text not in capsys.readouterr().err


def test_us42_ac4_gate_passes_on_current_rules() -> None:
    assert run_gate(RulesProvider()) == []


def test_us42_ac4_gate_fails_when_rejection_rules_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    kept = tuple(r for r in rules.RULES if r.label is not Label.REJECTION)
    monkeypatch.setattr(rules, "RULES", kept)
    failures = run_gate(RulesProvider())
    assert any("rejection_recall" in f for f in failures)


def test_us42_ac4_gate_fails_on_always_rejection_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = rules.Rule("rej.bad", Label.REJECTION, re.compile(r".*"), 0.95)
    monkeypatch.setattr(rules, "RULES", (bad, *rules.RULES))
    failures = run_gate(RulesProvider())
    assert any("rejection_precision" in f for f in failures)


def test_us42_gate_tolerates_small_drops_and_enforces_precision_floor() -> None:
    base = load_baseline()["tune"]
    report = evaluate(RulesProvider(), load_cases(FIXTURES / "tune.jsonl"))
    assert gate_failures(report, base) == []
    assert gate_failures(report, {**base, "accuracy": base["accuracy"] + 0.05})
    assert gate_failures(report, {**base, "rejection_recall": base["rejection_recall"] + 0.03})


def test_us42_negated_offer_is_not_an_offer() -> None:
    inp = ClassificationInput("x.example", "Update", "We will not be extending an offer to you")
    assert RulesProvider().classify(inp).label is Label.REJECTION


def _empty_report(**overrides: object) -> Report:
    base = {
        "n": 100,
        "accuracy": 0.7,
        "coverage": 0.7,
        "rejection_precision": 1.0,
        "rejection_recall": 0.9,
        "auto_error_rate": 0.0,
        "per_label": {str(lb): LabelStats(1.0, 1.0, 5) for lb in Label},
        "confusion": {},
    }
    return Report(**{**base, **overrides})  # type: ignore[arg-type]


_BASE = {
    "accuracy": 0.7,
    "rejection_precision": 1.0,
    "rejection_recall": 0.9,
    "interview_precision": 1.0,
    "offer_precision": 1.0,
    "auto_error_rate": 0.0,
}


def test_us42_gate_fails_on_interview_or_offer_precision_and_auto_error() -> None:
    labels = {str(lb): LabelStats(1.0, 1.0, 5) for lb in Label}
    labels["interview"] = LabelStats(0.85, 1.0, 5)
    assert any(
        "interview_precision" in f for f in gate_failures(_empty_report(per_label=labels), _BASE)
    )
    labels = {**labels, "interview": LabelStats(1.0, 1.0, 5), "offer": LabelStats(0.5, 1.0, 5)}
    assert any(
        "offer_precision" in f for f in gate_failures(_empty_report(per_label=labels), _BASE)
    )
    assert any(
        "auto_error_rate" in f for f in gate_failures(_empty_report(auto_error_rate=0.05), _BASE)
    )


def test_us42_gate_fails_on_too_few_cases_and_undefined_precision_rules() -> None:
    assert gate_failures(_empty_report(n=0), _BASE, min_cases=60)
    assert gate_failures(_empty_report(rejection_precision=None, rejection_recall=0.0), _BASE)
    assert not gate_failures(_empty_report(rejection_precision=None), _BASE)


def test_us42_undefined_metrics_are_none_and_print_na(capsys: pytest.CaptureFixture[str]) -> None:
    report = evaluate(_Scripted({"1": None}), [_case(1, Label.OFFER)])
    assert report.rejection_precision is None
    assert report.per_label["offer"].precision is None
    assert report.auto_error_rate is None
    assert "n/a" in format_table(report, "x")


# Generic negated interview/offer wording in a rejection context (own wording).
@pytest.mark.parametrize(
    "snippet",
    [
        "Regrettably your application will not advance to the next round.",
        "We have decided against extending an offer for the internship.",
        "We are not able to invite you to an interview this cycle.",
        "Unfortunately we cannot schedule an interview with you.",
    ],
)
def test_us42_negated_interview_or_offer_never_auto_applies(snippet: str) -> None:
    result = RulesProvider().classify(ClassificationInput("x.example", "Update", snippet))
    assert result.needs_review or result.label is Label.REJECTION
    assert result.label not in (Label.INTERVIEW, Label.OFFER) or result.needs_review
