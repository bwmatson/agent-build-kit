"""Installing the timers for a planning repo that is also a code repo.

The units run in a detached worktree of the repository, outside the person's working copy, so a
tick never touches the branch they are working on. Installing makes (or reuses) that worktree,
records it in the marker and points every unit at it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from agent_build_kit import timers
from agent_build_kit.pipeline.planning_repo import common_dir
from agent_build_kit.pipeline.planning_sync import read_pipeline_marker
from agent_build_kit.pipeline.shell import git as run_git
from tests.factories import commit_files, git, init_repo
from tests.planning_worktree_support import (
    InRepo,
    installation_at,
    publish_elsewhere,
    working_copy_of,
)


class Machine:
    """A temporary repository, unit directory and data directory, and the manager's calls."""

    def __init__(self, base: Path, *, origin: bool = True) -> None:
        bare, self.working_copy = working_copy_of(base, origin=origin)
        self.data = base / "data"
        self.dest = base / "units"
        self.worktree = self.data / "app" / "planning"
        self.setup = InRepo(origin=bare, working_copy=self.working_copy, worktree=self.worktree)
        self.calls: list[list[str]] = []

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    def install(self, root: Path | None = None, **options) -> timers.InRepoInstall:
        inst = installation_at(root or self.working_copy, self.working_copy)
        return timers.install_in_repo(
            inst, dest=self.dest, run=self.run, data_dir=self.data, **options
        )

    def remove(self, **options) -> timers.InRepoRemoval:
        inst = installation_at(self.working_copy, self.working_copy)
        return timers.remove_in_repo(inst, dest=self.dest, run=self.run, **options)

    def units(self, suffix: str) -> list[Path]:
        return sorted(self.dest.glob(f"abk-*{suffix}"))

    def worktrees(self) -> list[str]:
        listed = git(self.working_copy, "worktree", "list", "--porcelain")
        return [line for line in listed.splitlines() if line.startswith("worktree ")]


@pytest.fixture
def machine(tmp_path: Path) -> Machine:
    return Machine(tmp_path)


def test_a_first_install_makes_the_worktree_at_the_fetched_tip(machine: Machine) -> None:
    tip = publish_elsewhere(machine.setup, {"NEWS.md": "news\n"})

    result = machine.install()

    assert result.worktree == machine.worktree
    assert result.created
    assert git(machine.worktree, "rev-parse", "HEAD") == tip
    assert run_git(machine.worktree, "symbolic-ref", "-q", "HEAD", check=False).returncode != 0


def test_the_marker_names_the_worktree(machine: Machine) -> None:
    machine.install()

    assert read_pipeline_marker(machine.working_copy) == machine.worktree.resolve()


def test_four_services_and_four_timers_run_in_the_worktree_and_the_timers_are_enabled(
    machine: Machine,
) -> None:
    machine.install()

    services, scheduled = machine.units(".service"), machine.units(".timer")
    assert len(services) == 4
    assert len(scheduled) == 4
    for service in services:
        assert f"WorkingDirectory={machine.worktree.resolve()}\n" in service.read_text()
    for timer in scheduled:
        assert ["systemctl", "--user", "enable", "--now", timer.name] in machine.calls


def test_the_working_copy_is_left_as_it_was(machine: Machine) -> None:
    before = (
        git(machine.working_copy, "status", "--porcelain"),
        git(machine.working_copy, "rev-parse", "HEAD"),
        git(machine.working_copy, "symbolic-ref", "HEAD"),
    )

    machine.install()

    assert before == (
        git(machine.working_copy, "status", "--porcelain"),
        git(machine.working_copy, "rev-parse", "HEAD"),
        git(machine.working_copy, "symbolic-ref", "HEAD"),
    )


def test_a_second_install_from_the_working_copy_changes_nothing(machine: Machine) -> None:
    machine.install()
    files = sorted(path.name for path in machine.dest.iterdir())

    again = machine.install()

    assert not again.created
    assert again.worktree == machine.worktree
    assert again.change.written == ()
    assert len(again.change.unchanged) == 8
    assert sorted(path.name for path in machine.dest.iterdir()) == files
    assert len(machine.worktrees()) == 2


def test_an_install_from_the_pipeline_worktree_reports_every_unit_unchanged(
    machine: Machine,
) -> None:
    machine.install()
    files = sorted(path.name for path in machine.dest.iterdir())

    again = machine.install(root=machine.worktree)

    assert not again.created
    assert again.worktree == machine.worktree
    assert again.change.written == ()
    assert len(again.change.unchanged) == 8
    assert sorted(path.name for path in machine.dest.iterdir()) == files
    assert len(machine.worktrees()) == 2


def test_a_path_that_is_not_a_worktree_is_refused_and_no_unit_is_written(
    machine: Machine,
) -> None:
    machine.worktree.mkdir(parents=True)
    (machine.worktree / "mine.txt").write_text("mine\n")

    with pytest.raises(timers.PlanningWorktreeRefused, match=re.escape(str(machine.worktree))):
        machine.install()

    assert not machine.dest.exists()
    assert (machine.worktree / "mine.txt").read_text() == "mine\n"
    assert read_pipeline_marker(machine.working_copy) is None


def test_a_worktree_of_another_repository_is_refused(machine: Machine, tmp_path: Path) -> None:
    other = init_repo(tmp_path / "other")
    commit_files(other, "start", {"a.txt": "a\n"})
    machine.worktree.parent.mkdir(parents=True)
    git(other, "worktree", "add", "-q", "--detach", str(machine.worktree), "HEAD")

    with pytest.raises(timers.PlanningWorktreeRefused, match=re.escape(str(machine.worktree))):
        machine.install()

    assert not machine.dest.exists()
    assert read_pipeline_marker(machine.working_copy) is None


def test_a_dirty_worktree_is_not_moved_and_the_install_says_why(machine: Machine) -> None:
    machine.install()
    kept = git(machine.worktree, "rev-parse", "HEAD")
    (machine.worktree / "README.md").write_text("edited by hand\n")
    publish_elsewhere(machine.setup, {"README.md": "changed upstream\n"})

    result = machine.install()

    assert git(machine.worktree, "rev-parse", "HEAD") == kept
    assert (machine.worktree / "README.md").read_text() == "edited by hand\n"
    assert any("dirty" in note.lower() for note in result.notes)
    assert len(result.change.unchanged) == 8


def test_a_dry_run_creates_no_worktree_marker_or_unit(machine: Machine) -> None:
    result = machine.install(dry_run=True)

    assert result.worktree == machine.worktree
    assert not machine.worktree.exists()
    assert read_pipeline_marker(machine.working_copy) is None
    assert not machine.dest.exists()
    assert len(machine.worktrees()) == 1


def test_remove_takes_the_units_and_the_marker_and_leaves_the_worktree(machine: Machine) -> None:
    machine.install()

    removed = machine.remove()

    assert removed.worktree == machine.worktree
    assert len(removed.change.removed) == 8
    assert machine.units(".service") == []
    assert machine.units(".timer") == []
    assert read_pipeline_marker(machine.working_copy) is None
    assert machine.worktree.is_dir()
    assert machine.worktree.resolve() in {
        Path(line.removeprefix("worktree ")).resolve() for line in machine.worktrees()
    }


def test_a_repository_with_no_origin_uses_the_local_default_branch(tmp_path: Path) -> None:
    machine = Machine(tmp_path, origin=False)
    commit_files(machine.working_copy, "local only", {"LOCAL.md": "local\n"})
    tip = git(machine.working_copy, "rev-parse", "main")

    machine.install()

    assert git(machine.worktree, "rev-parse", "HEAD") == tip
    assert common_dir(machine.worktree) == common_dir(machine.working_copy)


def test_a_separate_planning_repo_installs_byte_for_byte_as_before(tmp_path: Path) -> None:
    code = init_repo(tmp_path / "code")
    commit_files(code, "start", {"a.txt": "a\n"})
    root = tmp_path / "planning-repo"
    inst = installation_at(root, code)
    data = tmp_path / "data"
    dest = tmp_path / "units"

    result = timers.install_in_repo(
        inst,
        dest=dest,
        run=lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, "", ""),
        data_dir=data,
    )

    assert result.worktree is None
    assert not data.exists()
    assert {path.name: path.read_text() for path in dest.iterdir()} == timers.render(root)


def test_a_worktree_without_abk_yaml_says_it_is_not_on_the_default_branch(
    machine: Machine,
) -> None:
    result = machine.install()

    assert any("abk.yaml" in note and "default branch" in note for note in result.notes)


def test_a_default_branch_that_is_neither_fetched_nor_local_is_refused_with_the_fix(
    machine: Machine,
) -> None:
    git(machine.working_copy, "checkout", "-q", "-b", "other")
    git(machine.working_copy, "branch", "-D", "main")
    git(machine.working_copy, "update-ref", "-d", "refs/remotes/origin/main")

    with pytest.raises(timers.PlanningWorktreeRefused, match="git fetch origin main"):
        machine.install()

    assert not machine.dest.exists()
