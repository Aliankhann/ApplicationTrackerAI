"""The deploy workflow's smoke test is valid YAML and valid bash, and reports each check."""

import subprocess
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"


def smoke_script() -> str:
    workflow: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text())
    steps = next(iter(workflow["jobs"].values()))["steps"]
    step = next(s for s in steps if s.get("name") == "Smoke test")
    assert step["if"] == "steps.cfg.outputs.configured == 'true'"  # skips when unconfigured
    return str(step["run"])


def test_smoke_script_is_strict_and_parses_under_bash() -> None:
    script = smoke_script()
    assert "set -euo pipefail" in script
    subprocess.run(["bash", "-n"], input=script, text=True, check=True)  # noqa: S607


def test_smoke_script_echoes_each_check_and_its_result() -> None:
    script = smoke_script()
    for line in (
        "/health -> ok",
        "landing page -> has #root",
        "CSP header present",
        "API origin substituted",
        "/me -> 401 json",
    ):
        assert line in script
    assert script.count('echo "check:') == 5
