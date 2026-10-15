"""A working copy says which installation is live, and the commands that write state refuse there.

The pipeline worktree is where the timers run; a person standing in the working copy would
otherwise read, or write, a second store.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as pipeline_cli
from agent_build_kit.cli import tracks as tracks_cli
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import CONFIG_ENV, dump
from agent_build_kit.pipeline.planning_sync import write_pipeline_marker
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.cli.test_doctor import Answers
from tests.factories import git, stored_unit, which_all
from tests.planning_worktree_support import installation_at, working_copy_of

COMMANDS = [
    pytest.param(["tick"], "cmd_tick", pipeline_cli, id="tick"),
    pytest.param(["track", "health"], "cmd_track", tracks_cli, id="track"),
    pytest.param(["verify", "feature"], "cmd_verify", pipeline_cli, id="verify"),
    pytest.param(["archive", "feature"], "cmd_archive", pipeline_cli, id="archive"),
]


class Live(NamedTuple):
    working_copy: Path
    worktree: Path

    @property
    def command(self) -> str:
        return f"abk --config {self.worktree / 'abk.yaml'}"


def installed(base: Path, *, marker: bool = True) -> Live:
    """A working copy that is its own planning root, and the worktree of it the timers run in,
    named by the marker unless `marker` is False. The working copy's `runs/` lists a unit of
    its own, which is not the pipeline's."""
    _, working_copy = working_copy_of(base)
    (working_copy / "abk.yaml").write_text(dump(installation_at(working_copy, working_copy).config))
    store = working_copy / "runs" / "units.json"
    store.unlink()
    UnitStore(store).upsert([stored_unit("pipeline-unit/1")])
    git(working_copy, "add", "abk.yaml", "runs")
    git(working_copy, "commit", "-qm", "config")
    worktree = base / "planning"
    git(working_copy, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    if marker:
        write_pipeline_marker(working_copy, worktree)
    UnitStore(store).upsert([stored_unit("working-copy-only/1")])
    return Live(working_copy, worktree)


@pytest.fixture(autouse=True)
def no_ambient_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONFIG_ENV, raising=False)
    monkeypatch.setattr(pipeline_cli, "current_usage", lambda: None)


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Live:
    setup = installed(tmp_path)
    monkeypatch.chdir(setup.working_copy)
    return setup


def ran(patch: pytest.MonkeyPatch, module, name: str) -> list[str]:
    """Replace the command with one that records that it ran and succeeds."""
    calls: list[str] = []
    patch.setattr(module, name, lambda args, inst: calls.append(name) or 0)
    return calls


def live_checks(checks: list[Check]) -> list[Check]:
    return [check for check in checks if "live" in check.name]


def test_status_names_the_live_worktree_and_the_command_that_reaches_it(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status"]) == 0

    out = capsys.readouterr().out
    assert str(live.worktree) in out
    assert f"{live.command} status" in out


def test_status_lists_no_unit_from_the_working_copys_runs(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["status"])

    assert "working-copy-only" not in capsys.readouterr().out


def test_status_with_a_config_named_runs_as_asked_and_says_it_is_not_the_live_one(
    live: Live, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--config", str(live.working_copy / "abk.yaml"), "status"]) == 0

    out = capsys.readouterr().out
    assert "working-copy-only/1" in out
    assert "not the live" in out


def test_doctor_reports_the_live_installation_in_one_check(live: Live) -> None:
    checks = run_doctor(live.working_copy / "abk.yaml", run=Answers(), which=which_all)

    found = live_checks(checks)
    assert len(found) == 1
    assert str(live.worktree) in found[0].detail + found[0].fix
    assert f"{live.command} doctor" in found[0].detail + found[0].fix


@pytest.mark.parametrize(("argv", "name", "module"), COMMANDS)
def test_the_command_refuses_in_the_working_copy_and_runs_nothing(
    live: Live,
    argv: list[str],
    name: str,
    module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = ran(monkeypatch, module, name)

    assert main(argv) != 0

    captured = capsys.readouterr()
    assert calls == []
    assert str(live.worktree) in captured.out + captured.err
    assert f"{live.command} {argv[0]}" in captured.out + captured.err


@pytest.mark.parametrize(("argv", "name", "module"), COMMANDS)
def test_a_config_named_on_the_command_line_runs_it_and_says_it_is_not_the_live_one(
    live: Live,
    argv: list[str],
    name: str,
    module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = ran(monkeypatch, module, name)

    assert main(["--config", str(live.working_copy / "abk.yaml"), *argv]) == 0

    captured = capsys.readouterr()
    assert calls == [name]
    assert "not the live" in captured.out + captured.err


@pytest.mark.parametrize(("argv", "name", "module"), COMMANDS)
def test_a_config_named_in_the_environment_runs_it_and_says_it_is_not_the_live_one(
    live: Live,
    argv: list[str],
    name: str,
    module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = ran(monkeypatch, module, name)
    monkeypatch.setenv(CONFIG_ENV, str(live.working_copy / "abk.yaml"))

    assert main(argv) == 0

    captured = capsys.readouterr()
    assert calls == [name]
    assert "not the live" in captured.out + captured.err
