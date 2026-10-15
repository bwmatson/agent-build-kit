"""Unit names for installations whose root is a pipeline worktree: named for the repository,
because every pipeline worktree is called the same."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import timers
from tests.planning_worktree_support import in_repo


def install_files(root: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name, text in timers.render(root).items():
        (dest / name).write_text(text)


def test_two_repositories_with_a_worktree_called_planning_are_named_apart(tmp_path: Path) -> None:
    first = in_repo(tmp_path / "one", name="app").worktree
    second = in_repo(tmp_path / "two", name="service").worktree
    separate = tmp_path / "meta"
    separate.mkdir()

    assert first.name == second.name == "planning"
    assert timers.unit_names(first) == [f"abk-app-{base}" for base in timers.BASE_UNITS]
    assert timers.unit_names(second) == [f"abk-service-{base}" for base in timers.BASE_UNITS]
    assert set(timers.render(first)) == set(timers.unit_names(first))
    assert timers.unit_names(separate) == [f"abk-meta-{base}" for base in timers.BASE_UNITS]


def test_each_installation_finds_its_own_units_only(tmp_path: Path) -> None:
    first = in_repo(tmp_path / "one", name="app").worktree
    second = in_repo(tmp_path / "two", name="service").worktree
    dest = tmp_path / "units"
    install_files(first, dest)
    install_files(second, dest)

    mine = timers.installed_units(first, dest)
    theirs = timers.installed_units(second, dest)

    assert {unit.name for unit in mine} == set(timers.unit_names(first))
    assert {unit.name for unit in theirs} == set(timers.unit_names(second))
    assert {timers.owner_of(unit) for unit in mine} == {first}
    assert {timers.owner_of(unit) for unit in theirs} == {second}
    assert timers.installed_root(dest, root=first) == first
    assert timers.installed_root(dest, root=second) == second
