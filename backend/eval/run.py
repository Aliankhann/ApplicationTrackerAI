"""Classifier eval harness: `uv run python -m eval.run [--split tune|holdout|all] [--data PATH]`.

Output never contains subjects or snippets; `--show-errors` prints case ids only.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.providers.classifier.base import ClassifierProvider
from app.providers.classifier.rules import RulesProvider
from app.providers.classifier.types import ClassificationInput, Label

FIXTURES = Path(__file__).parent / "fixtures"
BASELINE_PATH = Path(__file__).parent / "baseline.json"
SPLITS = ("tune", "holdout")
REVIEW = "needs_review"
MIN_CASES = {"tune": 120, "holdout": 60}
ACCURACY_TARGET = 0.90
REJECTION_PRECISION_TARGET = 0.95


@dataclass(frozen=True)
class Case:
    id: str
    from_domain: str
    subject: str
    snippet: str
    label: Label


@dataclass(frozen=True)
class LabelStats:
    precision: float | None  # None: undefined (no predictions / no gold cases)
    recall: float | None
    support: int


@dataclass(frozen=True)
class Report:
    n: int
    accuracy: float
    coverage: float
    rejection_precision: float | None
    rejection_recall: float | None
    auto_error_rate: float | None  # wrong auto-applied labels / auto-applied labels
    per_label: dict[str, LabelStats]
    confusion: dict[str, dict[str, int]]  # gold -> predicted (or "needs_review") -> count
    error_ids: list[str] = field(default_factory=list)


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


class CaseFormatError(Exception):
    """A case line is malformed; the message names file and line only, never values."""


def _parse_case(raw: Any) -> Case:
    fields = (raw["id"], raw["from_domain"], raw["subject"], raw["snippet"])
    if not all(isinstance(f, str) for f in fields):
        raise ValueError("case fields must be strings")
    return Case(*fields, Label(raw["label"]))


def load_cases(path: Path) -> list[Case]:
    cases: list[Case] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(_parse_case(json.loads(line)))
        except (ValueError, KeyError, TypeError) as exc:
            raise CaseFormatError(f"{path.name}:{number}: invalid case") from exc
    return cases


def load_split(split: str, data_dir: Path = FIXTURES) -> list[Case]:
    names = SPLITS if split == "all" else (split,)
    return [c for name in names for c in load_cases(data_dir / f"{name}.jsonl")]


def _predict(provider: ClassifierProvider, case: Case) -> str:
    result = provider.classify(ClassificationInput(case.from_domain, case.subject, case.snippet))
    if result.needs_review or result.label is None:
        return REVIEW
    return str(result.label)


def evaluate(provider: ClassifierProvider, cases: Sequence[Case]) -> Report:
    predictions = [(c, _predict(provider, c)) for c in cases]
    confusion: dict[str, Counter[str]] = {}
    for case, predicted in predictions:
        confusion.setdefault(str(case.label), Counter())[predicted] += 1
    predicted_totals: Counter[str] = Counter(p for _, p in predictions)
    per_label: dict[str, LabelStats] = {}
    for label in Label:
        name = str(label)
        hits = confusion.get(name, Counter())[name]
        support = sum(confusion.get(name, Counter()).values())
        per_label[name] = LabelStats(
            _ratio(hits, predicted_totals[name]), _ratio(hits, support), support
        )
    correct = sum(1 for c, p in predictions if p == str(c.label))
    reviewed = predicted_totals[REVIEW]
    rejection = per_label[str(Label.REJECTION)]
    auto = [(c, p) for c, p in predictions if p != REVIEW]
    return Report(
        n=len(predictions),
        accuracy=_ratio(correct, len(predictions)) or 0.0,
        coverage=_ratio(len(predictions) - reviewed, len(predictions)) or 0.0,
        rejection_precision=rejection.precision,
        rejection_recall=rejection.recall,
        auto_error_rate=_ratio(sum(1 for c, p in auto if p != str(c.label)), len(auto)),
        per_label=per_label,
        confusion={gold: dict(row) for gold, row in confusion.items()},
        error_ids=[c.id for c, p in predictions if p != str(c.label)],
    )


def format_table(report: Report, title: str) -> str:
    lines = [
        f"== {title} (n={report.n}) ==",
        f"accuracy {report.accuracy:.3f} (target {ACCURACY_TARGET})  "
        f"coverage {report.coverage:.3f}",
        f"rejection precision {_fmt(report.rejection_precision)} "
        f"(target {REJECTION_PRECISION_TARGET})  recall {_fmt(report.rejection_recall)}",
        f"auto-applied error rate {_fmt(report.auto_error_rate)}",
        f"{'label':<20}{'prec':>7}{'recall':>8}{'n':>5}",
    ]
    for name, s in report.per_label.items():
        lines.append(f"{name:<20}{_fmt(s.precision):>7}{_fmt(s.recall):>8}{s.support:>5}")
    lines.append("confusion (gold -> predicted: count)")
    for gold, row in sorted(report.confusion.items()):
        lines.append(f"  {gold}: " + ", ".join(f"{p}={n}" for p, n in sorted(row.items())))
    return "\n".join(lines)


def baseline_metrics(report: Report) -> dict[str, float]:
    values = {
        "accuracy": report.accuracy,
        "rejection_precision": report.rejection_precision,
        "rejection_recall": report.rejection_recall,
        "interview_precision": report.per_label[str(Label.INTERVIEW)].precision,
        "offer_precision": report.per_label[str(Label.OFFER)].precision,
        "auto_error_rate": report.auto_error_rate,
    }
    return {k: round(v, 4) for k, v in values.items() if v is not None}


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, dict[str, float]]:
    data: dict[str, dict[str, float]] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _drop(value: float | None, baseline: float, tol: float) -> bool:
    return value is not None and value < baseline - tol


def gate_failures(
    report: Report, baseline: dict[str, float], min_cases: int = 1, tol: float = 0.02
) -> list[str]:
    """Reasons the report fails the regression gate; empty means pass."""
    failures: list[str] = []
    if report.n < min_cases:
        return [f"only {report.n} cases, need at least {min_cases}"]
    recall_low = report.rejection_recall is None or _drop(
        report.rejection_recall, baseline["rejection_recall"], tol
    )
    floor = max(REJECTION_PRECISION_TARGET, baseline["rejection_precision"] - 0.01)
    precision = report.rejection_precision
    if (precision is None and recall_low) or (precision is not None and precision < floor):
        failures.append(f"rejection_precision {_fmt(precision)} < {floor:.3f}")
    if _drop(report.accuracy, baseline["accuracy"], tol):
        failures.append(f"accuracy {report.accuracy:.3f} dropped below baseline")
    if recall_low:
        failures.append(f"rejection_recall {_fmt(report.rejection_recall)} dropped below baseline")
    for label in (Label.INTERVIEW, Label.OFFER):
        value = report.per_label[str(label)].precision
        label_floor = max(0.90, baseline[f"{label}_precision"] - tol)
        if value is not None and value < label_floor:
            failures.append(f"{label}_precision {value:.3f} < {label_floor:.3f}")
    error = report.auto_error_rate
    if error is not None and error > baseline["auto_error_rate"] + tol:
        failures.append(f"auto_error_rate {error:.3f} > baseline {baseline['auto_error_rate']}")
    return failures


def run_gate(provider: ClassifierProvider, data_dir: Path = FIXTURES) -> list[str]:
    """Failures across both splits against the stored baseline; empty means pass."""
    baseline = load_baseline()
    failures: list[str] = []
    for name in SPLITS:
        report = evaluate(provider, load_cases(data_dir / f"{name}.jsonl"))
        failures += [f"{name}: {f}" for f in gate_failures(report, baseline[name], MIN_CASES[name])]
    return failures


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="eval.run", description="Evaluate the rules classifier.")
    p.add_argument("--split", choices=[*SPLITS, "all"], default="all")
    p.add_argument("--data", type=Path, default=FIXTURES, help="directory with tune/holdout jsonl")
    p.add_argument("--json", action="store_true", help="print metrics as JSON")
    p.add_argument("--show-errors", action="store_true", help="print ids of wrong cases only")
    p.add_argument("--write-baseline", action="store_true", help="store current metrics")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    names = SPLITS if args.split == "all" else (args.split,)
    try:
        reports = {
            name: evaluate(RulesProvider(), load_cases(args.data / f"{name}.jsonl"))
            for name in names
        }
    except CaseFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: cannot read {Path(exc.filename or 'data').name}", file=sys.stderr)
        return 2
    if args.write_baseline:
        BASELINE_PATH.write_text(
            json.dumps({n: baseline_metrics(r) for n, r in reports.items()}, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        payload: dict[str, Any] = {n: asdict(r) for n, r in reports.items()}
        print(json.dumps(payload, indent=2))
        return 0
    for name, report in reports.items():
        print(format_table(report, name))
        if args.show_errors:
            print("errors: " + (" ".join(report.error_ids) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
