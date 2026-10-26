"""`install_in_repo` moves a pipeline worktree left in the old place, the planning home itself, to
`<planning home>/worktree`, and does it safely (spec: planning-state-home)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit import timers
from agent_build_kit.pipeline.planning_sync import read_pipeline_marker
from tests.cli.install_timers_support import Systemctl
from tests.factories import git
from tests.planning_worktree_support import add_pipeline_worktree, installation_at, working_copy_of


class Machine:
    """A working copy whose pipeline worktree sits at the old default (when `legacy`), units
    installed for it, and a manager that reports `active` units as running."""

    def __init__(self, base: Path, data: Path, *, legacy: bool = True, active: str = "") -> None:
        _, self.working_copy = working_copy_of(base / "repos")
        self.dest = base / "units"
        self.old = data / "app" / "planning"
        self.new = self.old / "worktree"
        self.manager = Systemctl()
        if legacy:
            self.old.parent.mkdir(parents=True)
            add_pipeline_worktree(self.working_copy, self.old)
            timers.install(self.old, dest=self.dest, run=self.manager)
        if active:
            self.manager.active.add(f"abk-app-{active}")
        self.manager.calls.clear()

    def install(self, **options) -> timers.InRepoInstall:
        inst = installation_at(self.working_copy, self.working_copy)
        return timers.install_in_repo(inst, dest=self.dest, run=self.manager, **options)

    def unit_files(self) -> dict[str, str]:
        return {path.name: path.read_text() for path in sorted(self.dest.iterdir())}

    def listed(self) -> list[str]:
        out = git(self.working_copy, "worktree", "list", "--porcelain")
        return [line.removeprefix("worktree ") for line in out.splitlines() if line.startswith("w")]


@pytest.fixture
def machine(tmp_path: Path, data: Path) -> Machine:
    return Machine(tmp_path, data)


def test_an_old_worktree_is_moved_into_the_planning_home(machine: Machine) -> None:
    names = sorted(machine.unit_files())

    result = machine.install()

    assert result.worktree == machine.new
    assert not result.created
    assert (machine.new / "README.md").is_file()
    assert machine.listed().count(str(machine.new.resolve())) == 1
    assert str(machine.old.resolve()) not in machine.listed()
    assert not machine.old.with_name("planning.moving").exists()
    assert read_pipeline_marker(machine.working_copy) == machine.new.resolve()
    assert sorted(machine.unit_files()) == names
    for name, text in machine.unit_files().items():
        if name.endswith(".service"):
            assert f"WorkingDirectory={machine.new.resolve()}\n" in text


def test_an_active_unit_refuses_and_changes_nothing(tmp_path: Path, data: Path) -> None:
    machine = Machine(tmp_path, data, active="tick.service")
    units = machine.unit_files()

    with pytest.raises(timers.PlanningWorktreeRefused) as refused:
        machine.install()

    assert "systemctl --user stop" in str(refused.value)
    assert "abk-app-tick.service" in str(refused.value)
    assert machine.listed().count(str(machine.old.resolve())) == 1
    assert not machine.new.exists()
    assert read_pipeline_marker(machine.working_copy) == machine.old.resolve()
    assert machine.unit_files() == units


def test_a_second_call_changes_nothing(machine: Machine) -> None:
    machine.install()
    units, listed = machine.unit_files(), machine.listed()
    machine.manager.calls.clear()

    again = machine.install()

    assert again.worktree == machine.new
    assert not again.created
    assert again.change.written == ()
    assert machine.unit_files() == units
    assert machine.listed() == listed
    assert read_pipeline_marker(machine.working_copy) == machine.new.resolve()
    assert not [call for call in machine.manager.calls if "is-active" in call]


def test_a_dry_run_says_would_move_and_writes_nothing(machine: Machine) -> None:
    units = machine.unit_files()

    result = machine.install(dry_run=True)

    assert f"would move {machine.old} to {machine.new}" in " ".join(result.notes)
    assert machine.listed().count(str(machine.old.resolve())) == 1
    assert not machine.new.exists()
    assert read_pipeline_marker(machine.working_copy) == machine.old.resolve()
    assert machine.unit_files() == units


def test_a_failure_after_the_first_move_puts_the_worktree_back(
    machine: Machine, monkeypatch: pytest.MonkeyPatch
) -> None:
    units = machine.unit_files()
    moves: list[tuple[str, ...]] = []
    real = timers.git

    def failing_second_move(repo: Path, *args: str, check: bool = True, **kwargs):
        if args[:2] == ("worktree", "move"):
            moves.append(args)
            if len(moves) == 2:
                failed = subprocess.CompletedProcess(["git", *args], 1, "", "fatal: injected")
                if check:
                    raise subprocess.CalledProcessError(1, failed.args, "", failed.stderr)
                return failed
        return real(repo, *args, check=check, **kwargs)

    monkeypatch.setattr(timers, "git", failing_second_move)

    with pytest.raises((timers.PlanningWorktreeRefused, subprocess.CalledProcessError)):
        machine.install()

    assert len(moves) >= 2
    assert machine.listed().count(str(machine.old.resolve())) == 1
    assert (machine.old / "README.md").is_file()
    assert not machine.new.exists()
    assert not machine.old.with_name("planning.moving").exists()
    assert read_pipeline_marker(machine.working_copy) == machine.old.resolve()
    assert machine.unit_files() == units


@pytest.mark.parametrize("legacy", [True, False], ids=["over an old worktree", "fresh"])
def test_a_directory_at_the_new_path_that_is_not_a_worktree_is_refused(
    tmp_path: Path, data: Path, legacy: bool
) -> None:
    machine = Machine(tmp_path, data, legacy=legacy)
    machine.new.mkdir(parents=True)
    (machine.new / "mine.txt").write_text("mine\n")
    units = machine.unit_files() if legacy else {}

    with pytest.raises(timers.PlanningWorktreeRefused, match=str(machine.new)):
        machine.install()

    assert (machine.new / "mine.txt").read_text() == "mine\n"
    assert (machine.unit_files() if machine.dest.exists() else {}) == units
    marker = read_pipeline_marker(machine.working_copy)
    assert marker == (machine.old.resolve() if legacy else None)


def test_a_fresh_install_makes_the_worktree_in_the_planning_home(
    tmp_path: Path, data: Path
) -> None:
    machine = Machine(tmp_path, data, legacy=False)

    result = machine.install()

    assert result.created
    assert result.worktree == machine.new
    assert machine.listed().count(str(machine.new.resolve())) == 1
    assert read_pipeline_marker(machine.working_copy) == machine.new.resolve()
