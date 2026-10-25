"""With the sandbox on by default, `abk doctor` names the outcome for each repo, `abk status`
shows coverage `none` where no backend exists, and `abk init` writes no `sandbox:` block (spec:
sandbox-default)."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import load
from agent_build_kit.sandboxes import Coverage
from agent_build_kit.settings import reload
from tests.cli.test_doctor import Answers, workspace  # noqa: F401 — fixture
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures
from tests.conftest import make_installation
from tests.factories import recognised_planning, which_all
from tests.runtimes.selectable import SelectableRuntime, select
from tests.sandboxes.stand_in import StandInBackend

ELSEWHERE = "no-such-platform"
REPOS = ("app", "platform")


@pytest.fixture
def working_backend() -> Iterator[None]:
    with sandboxes.isolated():
        sandboxes.register(StandInBackend("landlock", ""))
        yield


@pytest.fixture
def no_backend() -> Iterator[None]:
    with sandboxes.isolated():
        sandboxes.register(StandInBackend("landlock", ELSEWHERE))
        sandboxes.register(StandInBackend("seatbelt", ELSEWHERE))
        yield


@pytest.fixture
def failing_backend() -> Iterator[None]:
    with sandboxes.isolated():
        sandboxes.register(StandInBackend("landlock", "", ok=False))
        yield


def sandbox_check(config: Path) -> Check:
    """The one sandbox check of a workspace that writes no `sandbox` block."""
    checks = run_doctor(config, run=Answers(), which=which_all)
    (found,) = [c for c in checks if "sandbox" in c.name]
    return found


def test_doctor_names_a_working_backend_and_every_repo_it_confines(
    workspace: Path,  # noqa: F811 — fixture
    working_backend: None,
) -> None:
    found = sandbox_check(workspace / "abk.yaml")

    assert found.status == "ok"
    assert "landlock" in found.detail
    assert all(repo in found.detail for repo in REPOS)


def test_doctor_says_a_machine_with_no_backend_runs_every_repo_unconfined(
    workspace: Path,  # noqa: F811 — fixture
    no_backend: None,
) -> None:
    found = sandbox_check(workspace / "abk.yaml")

    assert found.status in ("ok", "info")
    assert "unconfined" in found.detail
    assert all(repo in found.detail for repo in REPOS)


def test_doctor_fails_a_backend_that_does_not_work_with_the_cause_and_the_fix(
    workspace: Path,  # noqa: F811 — fixture
    failing_backend: None,
) -> None:
    found = sandbox_check(workspace / "abk.yaml")

    assert found.status == "FAIL"
    assert "stand-in off" in found.detail
    assert "turn on" in found.fix


def test_status_shows_coverage_none_where_no_backend_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_backend: None,
) -> None:
    monkeypatch.setenv("ABK_RUNTIME", "covered")
    reload(None)
    select(monkeypatch, SelectableRuntime("covered", sandbox_coverage=Coverage.PROCESS))
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), make_installation(tmp_path))

    shown = capsys.readouterr()
    assert any("sandbox_coverage: none" in line for line in (shown.out + shown.err).splitlines())
    monkeypatch.delenv("ABK_RUNTIME")
    reload(None)


def test_init_writes_no_sandbox_block_and_the_workspace_is_confined(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
) -> None:
    planning = recognised_planning(tmp_path / "planning")

    assert main([*init_args(planning, app), "--yes"]) == 0

    assert "sandbox:" not in (planning / "abk.yaml").read_text()
    assert load(planning / "abk.yaml").sandbox.enabled is True
