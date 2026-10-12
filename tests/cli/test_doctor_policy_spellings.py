"""`abk doctor` names the spelling of a forbidden command the runtime let through."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import run_doctor
from tests.factories import init_repo
from tests.runtimes.selectable import (
    AMEND,
    AMEND_REFUSED,
    AMEND_UNREFUSED,
    SelectableRuntime,
    select,
    spelling_report,
)


def answer(argv, **kwargs):
    if argv[0] == "git":
        return subprocess.run(argv, **kwargs)
    return subprocess.CompletedProcess(argv, 0, "1.0.0\n", "")


def which_all(name: str) -> str | None:
    return f"/usr/bin/{name}"


def test_an_unrefused_spelling_fails_naming_the_class_and_the_spelling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("loose", reports=(spelling_report(),)))
    planning = init_repo(tmp_path / "planning")
    (planning / "abk.yaml").write_text(
        "repos: {}\n"
        + "runtime: loose\nruntimes:\n  loose:\n"
        + "    policy_fix: [scripts/constrain-agent.sh, --strict]\n"
    )

    checks = run_doctor(planning / "abk.yaml", run=answer, which=which_all)

    policy = next(check for check in checks if check.name == "runtime policy")
    assert policy.status == "FAIL"
    assert AMEND in policy.detail
    assert AMEND_UNREFUSED in policy.detail
    # The class's other spellings are grouped with it, as refused.
    for refused in AMEND_REFUSED:
        assert refused in policy.detail
    assert "scripts/constrain-agent.sh --strict" in policy.fix
