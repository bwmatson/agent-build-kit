"""A tick brings the pipeline worktree to the default branch's tip before it does anything else,
stops with one reason when it cannot, and leaves a person's working copy alone."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.factories import commit, git
from tests.planning_worktree_support import InRepo, in_repo, installation_at, publish_elsewhere


class Reads:
    """What a tick read and when: the worktree's HEAD at each read of the store or of the work."""

    def __init__(self, tree: Path) -> None:
        self.tree = tree
        self.heads: list[str] = []

    def record(self, *args, **kwargs) -> None:
        self.heads.append(git(self.tree, "rev-parse", "HEAD"))


def watch(patch: pytest.MonkeyPatch, tree: Path) -> Reads:
    """Replace the tick's reads of the store and of the work with a recorder that finds none."""
    reads = Reads(tree)
    patch.setattr(cli, "store_for", reads.record)
    patch.setattr(cli, "has_work", lambda *args, **kwargs: reads.record() or False)
    return reads


def tick(setup: InRepo, root: Path) -> int:
    inst = installation_at(root, setup.working_copy)
    return cli.cmd_tick(argparse.Namespace(dry_run=False, only=None), inst)


def test_a_tick_in_a_worktree_behind_the_tip_syncs_before_it_reads_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = in_repo(tmp_path)
    tip = publish_elsewhere(setup, {"a.txt": "a\n"})
    reads = watch(monkeypatch, setup.worktree)

    assert tick(setup, setup.worktree) == 0

    assert reads.heads and set(reads.heads) == {tip}


def test_a_stopped_sync_ends_the_tick_after_one_line_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    setup = in_repo(tmp_path)
    own = commit(setup.worktree, "own.txt")
    publish_elsewhere(setup, {"a.txt": "a\n"})
    units = (setup.worktree / "runs" / "units.json").read_bytes()
    reads = watch(monkeypatch, setup.worktree)

    assert tick(setup, setup.worktree) == 1

    stopped = [line for line in capsys.readouterr().out.splitlines() if "sync stopped" in line]
    assert len(stopped) == 1 and "planning sync stopped: " in stopped[0]
    assert reads.heads == []
    assert git(setup.worktree, "rev-parse", "HEAD") == own
    assert (setup.worktree / "runs" / "units.json").read_bytes() == units


def test_repeated_ticks_in_a_working_copy_leave_its_branch_and_files_as_they_were(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = in_repo(tmp_path)
    git(setup.working_copy, "checkout", "-q", "-b", "feature")
    (setup.working_copy / "README.md").write_text("edited by a person\n")
    publish_elsewhere(setup, {"a.txt": "a\n"})
    head = git(setup.working_copy, "rev-parse", "HEAD")
    reads = watch(monkeypatch, setup.working_copy)

    assert tick(setup, setup.working_copy) == 0
    assert tick(setup, setup.working_copy) == 0

    assert git(setup.working_copy, "symbolic-ref", "--short", "HEAD") == "feature"
    assert git(setup.working_copy, "rev-parse", "HEAD") == head
    assert git(setup.working_copy, "status", "--porcelain") == "M README.md"
    assert (setup.working_copy / "README.md").read_text() == "edited by a person\n"
    assert set(reads.heads) == {head}
