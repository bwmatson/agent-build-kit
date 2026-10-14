"""Doctor, init and `abk policy check` choose the check through one function, and doctor never
starts the agent."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import run_doctor
from agent_build_kit.runtimes import PolicyReport, policy_check
from agent_build_kit.runtimes.recommended_policy import patterns
from tests.cli.policy_static_cli import abk_yaml, agent_command, planning_for
from tests.cli.test_doctor import (  # noqa: F401 — fixture
    Answers,
    by_name,
    select_runtime,
    which_all,
    workspace,
)
from tests.cli.test_init import app, stubs  # noqa: F401 — fixtures
from tests.runtimes.policy_static_support import LABEL, agent_home, recording_program, write_config


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`policy_check.check_policy` replaced by one that passes and records the runtime's name."""
    names: list[str] = []

    def passing(runtime, entry, installation) -> PolicyReport:  # noqa: ANN001
        names.append(runtime.name)
        return PolicyReport(ok=True, source=LABEL)

    monkeypatch.setattr(policy_check, "check_policy", passing)
    return names


def test_doctor_calls_the_one_function(
    workspace: Path,  # noqa: F811 — fixture
    asked: list[str],
) -> None:
    select_runtime(workspace, "acp", f"    command: {agent_command()}\n")

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert asked == ["acp"]
    assert checks["runtime policy"].status == "ok"


def test_init_calls_the_one_function(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    asked: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planning = planning_for(tmp_path, app, monkeypatch, agent_command())

    assert main(["init", str(planning), "--policy-only"]) == 0

    assert asked == ["acp"]


def test_policy_check_calls_the_one_function(
    tmp_path: Path, asked: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(abk_yaml(tmp_path, agent_command())), "policy", "check"]) == 0

    assert asked == ["acp"]


def test_doctor_never_starts_a_command_that_records_a_start_and_fails(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program = recording_program(tmp_path / "bin")
    write_config(agent_home(tmp_path, monkeypatch), patterns())
    select_runtime(workspace, "acp", f"    command: {agent_command(str(program))}\n")

    checks = by_name(run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all))

    assert not (tmp_path / "started.log").exists()
    assert checks["runtime policy"].status == "ok"
