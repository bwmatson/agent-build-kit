"""`abk doctor` names the spelling of a forbidden command the runtime let through."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import run_doctor
from tests.cli.test_doctor import (  # noqa: F401 — fixture
    Answers,
    by_name,
    select_runtime,
    which_all,
    workspace,
)
from tests.runtimes.selectable import SelectableRuntime, amend_finding, select, spelling_report


def test_an_unrefused_spelling_fails_naming_the_class_and_the_spelling(
    workspace: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    select(monkeypatch, SelectableRuntime("loose", reports=(spelling_report(),)))
    select_runtime(workspace, "loose", "    policy_fix: [scripts/constrain-agent.sh, --strict]\n")

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    policy = checks["runtime policy"]
    assert policy.status == "FAIL"
    # Only the class with a spelling let through is listed; the others are not.
    assert policy.detail == f"not refused: {amend_finding()}"
    assert "merging a pull request" not in policy.detail
    assert "scripts/constrain-agent.sh --strict" in policy.fix


def test_every_spelling_refused_passes(
    workspace: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    select(monkeypatch, SelectableRuntime("tight", reports=(spelling_report(refused=True),)))
    select_runtime(workspace, "tight")

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["runtime policy"].status == "ok"
