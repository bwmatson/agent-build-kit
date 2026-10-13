"""What a failing `abk doctor` policy check tells the person to run: the installation's own fix
first, else the kit's apply command for an agent it can write to, else the patterns command and
the key to set."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import run_doctor
from tests.cli.policy_apply_fakes import AGENT, BARE
from tests.cli.test_doctor import (  # noqa: F401 — fixture
    Answers,
    by_name,
    select_runtime,
    which_all,
    workspace,
)
from tests.runtimes.selectable import SelectableRuntime, select, spelling_report

OWN_FIX = "scripts/constrain-agent.sh"


def fix_text(
    workspace: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    program: tuple[str, ...],
    own: bool = False,
) -> str:
    select(monkeypatch, SelectableRuntime("loose", reports=(spelling_report(),)))
    entry = f"    command: [{', '.join(program)}]\n"
    if own:
        entry += f"    policy_fix: [{OWN_FIX}, --strict]\n"
    select_runtime(workspace, "loose", entry)

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert checks["runtime policy"].status == "FAIL"
    return checks["runtime policy"].fix


def test_the_installations_own_fix_comes_first_and_the_kits_is_offered_after_it(
    workspace: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fix = fix_text(workspace, monkeypatch, AGENT.variants[0].argv, own=True)

    assert fix.startswith(f"{OWN_FIX} --strict")
    assert "abk policy apply" in fix


def test_with_no_fix_of_its_own_an_agent_with_an_applier_is_told_to_apply(
    workspace: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fix = fix_text(workspace, monkeypatch, AGENT.variants[0].argv)

    assert "abk policy apply" in fix
    assert "set `runtimes.loose.policy_fix`" not in fix


def test_an_agent_with_no_applier_is_told_the_patterns_command_then_the_key_to_set(
    workspace: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fix = fix_text(workspace, monkeypatch, BARE.variants[0].argv)

    assert "abk policy patterns" in fix
    assert "abk policy apply" not in fix
    assert "runtimes.loose.policy_fix" in fix
    assert fix.index("abk policy patterns") < fix.index("runtimes.loose.policy_fix")
