"""`abk attach release <unit>`: resolve a chat's lease without the server. With `--commit` it
commits and releases, with `--discard` it restores the tree and releases, each as one command;
without either it refuses a dirty tree and says what to choose."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from tests.attach_driver import changed_files, checked_out, head, leave_lease
from tests.conftest import make_installation
from tests.factories import git
from tests.serving import seed_pipeline

UNIT = "feature/2"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(
        tmp_path / "planning", planning={"worktree_root": str(tmp_path / "worktrees")}
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    seed_pipeline(installation)
    return installation


@pytest.fixture
def tree(inst: Installation) -> Path:
    """The unit's worktree holding a changed file and a new one, under a lease whose server
    has gone."""
    path = checked_out(inst, UNIT)
    (path / "base.txt").write_text("edited by a chat\n")
    (path / "new.py").write_text("NEW = 1\n")
    leave_lease(lease_dir(inst.state_dir), UNIT, files=2)
    return path


def attachment(inst: Installation):
    return Leases(lease_dir(inst.state_dir)).attachment(UNIT)


def test_commit_commits_every_change_and_releases_the_lease_in_one_command(
    inst: Installation, tree: Path
) -> None:
    before = head(tree)

    assert main(["attach", "release", UNIT, "--commit", "Rename the marker"]) == 0

    assert head(tree) != before
    assert git(tree, "log", "-1", "--format=%s").strip() == "Rename the marker"
    assert git(tree, "rev-parse", "HEAD~1").strip() == before
    assert sorted(git(tree, "show", "--name-only", "--format=", "HEAD").split()) == [
        "base.txt",
        "new.py",
    ]
    assert changed_files(tree) == []
    assert attachment(inst) is None


def test_discard_restores_the_tree_and_releases_the_lease_in_one_command(
    inst: Installation, tree: Path
) -> None:
    before = head(tree)

    assert main(["attach", "release", UNIT, "--discard"]) == 0

    assert head(tree) == before
    assert changed_files(tree) == []
    assert (tree / "base.txt").read_text() == "base\n"
    assert not (tree / "new.py").exists()
    assert attachment(inst) is None


def test_a_dirty_tree_without_either_flag_is_refused_and_says_what_to_choose(
    inst: Installation, tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = head(tree)

    assert main(["attach", "release", UNIT]) != 0

    said = capsys.readouterr()
    words = (said.out + said.err).lower()
    assert "--commit" in words and "--discard" in words
    assert changed_files(tree) == ["base.txt", "new.py"], "nothing changed"
    assert head(tree) == before
    kept = attachment(inst)
    assert kept is not None and kept.changed == 2, "the lease is kept"


def test_a_clean_tree_is_released_without_either_flag(inst: Installation) -> None:
    path = checked_out(inst, UNIT)
    live = Leases(lease_dir(inst.state_dir))
    assert live.take(UNIT, "tab:a")

    assert main(["attach", "release", UNIT]) == 0

    assert changed_files(path) == []
    assert attachment(inst) is None


def test_releasing_a_unit_that_is_not_attached_says_so(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    checked_out(inst, UNIT)

    assert main(["attach", "release", UNIT]) == 0

    assert "not attached" in capsys.readouterr().out.lower()


def test_an_unknown_unit_is_refused(inst: Installation) -> None:
    assert main(["attach", "release", "feature/99", "--discard"]) != 0
