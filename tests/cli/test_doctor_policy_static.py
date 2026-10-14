"""`abk doctor`'s runtime-policy check reads the agent's configuration, says so, starts no
agent and keeps no answer."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.runtimes.recommended_policy import patterns
from tests.cli.policy_static_cli import UNKNOWN_PROGRAM, agent_command
from tests.cli.test_doctor import (  # noqa: F401 — fixture
    Answers,
    by_name,
    select_runtime,
    which_all,
    workspace,
)
from tests.runtimes.policy_static_support import (
    LABEL,
    agent_home,
    commands_of,
    config_file,
    write_config,
)
from tests.spelling_rows import AMEND

CANNOT = "cannot check: abk has no policy for this agent"


def policy_check(workspace: Path, command: list[str]) -> Check:  # noqa: F811 — fixture
    select_runtime(workspace, "acp", f"    command: {command}\n")
    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))
    return checks["runtime policy"]


def test_a_configuration_holding_the_recommendation_passes_and_says_what_it_read(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_config(agent_home(tmp_path, monkeypatch), patterns())

    check = policy_check(workspace, agent_command())

    assert check.status == "ok"
    assert LABEL in check.detail
    assert not list(workspace.rglob("policy-check*"))


def test_an_unrefused_class_fails_naming_it_and_the_spelling_with_the_fix(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_config(agent_home(tmp_path, monkeypatch), [p for p in patterns() if "amend" not in p])

    check = policy_check(workspace, agent_command())

    assert check.status == "FAIL"
    assert AMEND in check.detail
    assert all(command in check.detail for command in commands_of(AMEND))
    assert "run `abk policy apply`" in check.fix


def test_an_absent_configuration_fails_naming_the_path(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = agent_home(tmp_path, monkeypatch)

    check = policy_check(workspace, agent_command())

    assert check.status == "FAIL"
    assert str(config_file(home)) in check.detail


def test_an_unrecognised_command_warns_that_abk_has_no_policy_and_never_passes(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_config(agent_home(tmp_path, monkeypatch), patterns())

    check = policy_check(workspace, agent_command(UNKNOWN_PROGRAM))

    assert check.status == "warn"
    assert CANNOT in check.detail
