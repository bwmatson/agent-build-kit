"""A dirty worktree under a stale lease that is marked as holding changes is a chat's, not a
failure's: the unit is parked with the cause `attached`, and nothing is committed or continued
over it, whether or not a killed node's start is still recorded (docs/unit-graph.md).

The worktree, the commit and the branch count are the real ones over a real git repository,
as in `test_resume_over_leftovers.py`; the lease is the real one, left by a process that exited.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.shell import git_out
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import FAILED
from agent_build_kit.serve.chat import Chat
from tests.attach_driver import leave_lease
from tests.conftest import make_installation
from tests.graph.test_resume_over_leftovers import (
    STRAY,
    UNIT,
    edit_by_hand,
    killed_in,
    rework_event,
)
from tests.graph_driver import fresh, position, tick
from tests.leftovers_driver import LEFTOVER, Habitat, Hands


def leases_of(tmp_path: Path) -> Leases:
    return Leases(lease_dir(tmp_path / "state"))


def test_a_stale_lease_with_changes_parks_the_unit_as_attached_and_commits_nothing(
    tmp_path: Path,
) -> None:
    habitat = Habitat(tmp_path, Hands())
    recorder = fresh(tmp_path)
    assert tick(tmp_path, recorder, **habitat.overrides()).status == RunStatus.OPEN
    tick(tmp_path, recorder, event=rework_event(), **habitat.overrides())
    edit_by_hand(habitat)
    leave_lease(lease_dir(tmp_path / "state"), UNIT, files=1)
    asked = len(habitat.runtime.requests)
    commits = habitat.commits_on_branch()

    outcome = tick(tmp_path, recorder, leases=leases_of(tmp_path), **habitat.overrides())

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get(UNIT)
    assert stored.state != "failed"
    assert stored.cause == Cause("attached")
    words = f"{stored.note}\n{outcome.detail}".lower()
    assert "abk attach release" in words, "what to run when the server is not"
    assert "server" in words
    assert len(habitat.runtime.requests) == asked, "no agent was started over it"
    assert habitat.commits_on_branch() == commits, "nothing was committed"
    assert (habitat.tree / STRAY).read_text() == "mine\n", "the changes are as they were left"
    assert git_out(habitat.tree, "status", "--porcelain").split() == ["??", STRAY]


def test_a_stale_lease_with_changes_wins_over_a_killed_nodes_recorded_start(
    tmp_path: Path,
) -> None:
    """The files present are the chat's to commit or discard along with the killed run's:
    the tick does not resume the node over them."""
    habitat, recorder = killed_in(tmp_path, "implement")
    leave_lease(lease_dir(tmp_path / "state"), UNIT, files=1)
    asked = len(habitat.runtime.requests)

    outcome = tick(tmp_path, recorder, leases=leases_of(tmp_path), **habitat.overrides())

    assert outcome.status == RunStatus.HELD
    assert recorder.store.get(UNIT).cause == Cause("attached")
    assert len(habitat.runtime.requests) == asked, "the node was not resumed"
    assert (habitat.tree / LEFTOVER).exists(), "and its leftovers were not committed"
    assert git_out(habitat.tree, "status", "--porcelain").split() == ["??", LEFTOVER]


def test_taking_a_lease_over_a_killed_nodes_start_clears_it_and_keeps_the_leftovers(
    tmp_path: Path,
) -> None:
    """The files that run left are taken over with the chat's, so no later run of the node
    takes them for its own."""
    habitat, recorder = killed_in(tmp_path, "implement")
    before = position(tmp_path).state
    assert before is not None and before.running_node == "implement"
    recorder.store.set_state(UNIT, FAILED, note="killed", cause=Cause.FAILED)
    inst = make_installation(tmp_path, planning=dict(state_dir="state"))
    chat = Chat(inst, units=recorder.store.all, recorded_session=lambda unit_id: None)

    assert chat.claim(recorder.store.get(UNIT), "t1") is True

    state = position(tmp_path).state
    assert state is not None and state.running_node == ""
    assert (habitat.tree / LEFTOVER).exists()
    assert git_out(habitat.tree, "status", "--porcelain").split() == ["??", LEFTOVER]
