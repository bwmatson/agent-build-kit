"""`abk attach release` ends an attachment the way the page does: a commit is handed to the
unit's checks as the `adopted` event in the same command, a commit made and not delivered is
delivered once, and a unit the store has as running is left alone (docs/cli.md)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node
from agent_build_kit.graph.unit import thread_position
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.attach_driver import changed_files, checked_out, head, leave_lease
from tests.chat_serving import record_session
from tests.conftest import make_installation, workspace_config
from tests.environment_fakes import FakeEnvironment
from tests.factories import git
from tests.serving import seed_pipeline

UNIT = "feature/2"
SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d41"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(
        tmp_path / "planning", planning={"worktree_root": str(tmp_path / "worktrees")}
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    seed_pipeline(installation)
    record_session(installation, UNIT, SESSION, runtime="claude_code")
    return installation


@pytest.fixture
def tree(inst: Installation) -> Path:
    return checked_out(inst, UNIT)


def test_a_lock_the_branch_does_not_track_is_not_adopted_with_the_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = FakeEnvironment(tmp_path / "control", locks=("deps.lock",))
    root = tmp_path / "planning"
    repos = {
        name: repo.model_dump(mode="json") for name, repo in workspace_config(root).repos.items()
    }
    repos["app"]["environment"] = env.config()
    locked = make_installation(root, repos=repos, planning={"worktree_root": str(tmp_path / "wt")})
    (locked.root / "abk.yaml").write_text(dump(locked.config))
    monkeypatch.chdir(locked.root)
    seed_pipeline(locked)
    record_session(locked, UNIT, SESSION, runtime="claude_code")
    tree = checked_out(locked, UNIT)
    (tree / "notes.txt").write_text("left by a chat\n")
    (tree / "deps.lock").write_text("created by the sync\n")
    leave_lease(lease_dir(locked.state_dir), UNIT, files=2)

    assert main(["attach", "release", UNIT, "--commit", "Add a note"]) == 0

    assert git(tree, "show", "--name-only", "--format=", "HEAD").split() == ["notes.txt"]
    assert (tree / "deps.lock").read_text() == "created by the sync\n"


def waiting_at(inst: Installation) -> tuple[str, ...]:
    async def read() -> tuple[str, ...]:
        async with open_checkpointer(unit_graphs_path(inst.state_dir)) as saver:
            return tuple((await thread_position(saver, UNIT)).next)

    return asyncio.run(read())


def adoptions(inst: Installation) -> int:
    history = UnitStore(inst.state_dir / "units.json").history(UNIT)
    return sum(1 for entry in history if entry.get("cause") == Cause.ADOPTED.value)


def attachment(inst: Installation):
    return Leases(lease_dir(inst.state_dir)).attachment(UNIT)


def test_commit_hands_the_unit_to_its_checks_in_the_same_command(
    inst: Installation, tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tree / "notes.txt").write_text("left by a chat\n")
    leave_lease(lease_dir(inst.state_dir), UNIT, files=1)
    assert waiting_at(inst) == (Node.AWAIT_REVIEW,)

    assert main(["attach", "release", UNIT, "--commit", "Add a note"]) == 0

    assert changed_files(tree) == []
    assert attachment(inst) is None
    assert waiting_at(inst) == (Node.CHECKS,)
    assert adoptions(inst) == 1
    message = git(tree, "log", "-1", "--format=%B")
    assert f"Unit: {UNIT}" in message and "Adopted-From: " in message
    assert head(tree)[:9] in capsys.readouterr().out


def test_a_commit_made_and_not_delivered_is_delivered_once_by_a_release_without_flags(
    inst: Installation, tree: Path
) -> None:
    (tree / "notes.txt").write_text("a change\n")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", "Add a note")
    leave_lease(lease_dir(inst.state_dir), UNIT, commit=head(tree))
    made = head(tree)

    assert main(["attach", "release", UNIT]) == 0
    assert main(["attach", "release", UNIT]) == 0

    assert head(tree) == made, "no second commit"
    assert attachment(inst) is None, "the record is removed"
    assert waiting_at(inst) == (Node.CHECKS,)
    assert adoptions(inst) == 1, "delivered once"


def test_a_unit_paused_part_way_through_a_node_is_left_alone_by_either_flag(
    inst: Installation, tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No branch lock is held, but the agent's half-done edits are in the tree and resuming
    the node is the tick's job."""
    (tree / "notes.txt").write_text("half done\n")
    leave_lease(lease_dir(inst.state_dir), UNIT, files=1)
    UnitStore(inst.state_dir / "units.json").set_state(
        UNIT, RUNNING, note="waiting out the usage window", cause=Cause.USAGE
    )
    before = head(tree)

    discarded = main(["attach", "release", UNIT, "--discard"])
    committed = main(["attach", "release", UNIT, "--commit", "half done"])

    assert (discarded, committed) == (1, 1)
    assert "running" in capsys.readouterr().out.lower()
    assert changed_files(tree) == ["notes.txt"], "the node's work stays"
    assert head(tree) == before
    kept = attachment(inst)
    assert kept is not None and kept.changed == 1
