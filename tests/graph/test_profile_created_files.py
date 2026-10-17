"""A file the profile's commands create is the pipeline's in a repository with no environment
section (spec: pipeline-environment).

A unit is built in a real git worktree with the real commit step; only the agent, the review
and unit-test are stand-ins. The profile's commands are not run, so the test puts the file they
create into the worktree between the ticks. The unit is built in one tick and asked for a
rework in the next, as a person's comment does, so the worktree check runs over what the
first tick left.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.pipeline.shell import git_out
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from tests.created_files_fakes import LOCK, MAKES_LOCK, configured, registered
from tests.factories import unit
from tests.graph.test_resume_over_leftovers import rework_event
from tests.graph_driver import fresh, tick
from tests.leftovers_driver import Habitat, Hands
from tests.runner_fakes import Recorder

UNIT = unit().id
STRAY = "stray.txt"


@pytest.fixture(autouse=True)
def profiles_registered() -> Iterator[None]:
    with registered():
        yield


def built(tmp_path: Path) -> tuple[Habitat, Recorder]:
    """A unit built and waiting in review, in a repository with no environment section."""
    habitat = Habitat(tmp_path, Hands(), config=configured(tmp_path / "meta", MAKES_LOCK.name))
    recorder = fresh(tmp_path)
    assert tick(tmp_path, recorder, **habitat.overrides()).status == RunStatus.OPEN
    return habitat, recorder


def reworked(tmp_path: Path, habitat: Habitat, recorder: Recorder) -> RunOutcome:
    """The tick that delivers a person's rework comment, and the one that does the rework."""
    tick(tmp_path, recorder, event=rework_event(), **habitat.overrides())
    return tick(tmp_path, recorder, **habitat.overrides())


def test_an_untracked_file_the_profile_names_does_not_hold_the_rework(tmp_path: Path) -> None:
    habitat, recorder = built(tmp_path)
    (habitat.tree / LOCK).write_text("created by a unit-test command\n")

    outcome = reworked(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.OPEN
    assert recorder.store.get(UNIT).cause is not Cause.DIRTY_WORKTREE
    assert (habitat.tree / "rework.txt").exists(), "the rework step ran"
    assert (habitat.tree / LOCK).exists(), "the file is still in the worktree"
    held = git_out(habitat.tree, "ls-tree", "-r", "--name-only", "HEAD").split()
    assert LOCK not in held, "and in no commit of the unit"


def test_another_uncommitted_file_still_holds_the_unit_and_is_the_only_one_named(
    tmp_path: Path,
) -> None:
    habitat, recorder = built(tmp_path)
    (habitat.tree / LOCK).write_text("created by a unit-test command\n")
    (habitat.tree / STRAY).write_text("mine\n")
    asked = len(habitat.runtime.requests)

    outcome = reworked(tmp_path, habitat, recorder)

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get(UNIT)
    assert stored.cause is Cause.DIRTY_WORKTREE
    words = f"{stored.note}\n{outcome.detail}"
    assert STRAY in words
    assert LOCK not in words, "the file the profile names is not a leftover"
    assert len(habitat.runtime.requests) == asked, "no agent was started over it"
    assert (habitat.tree / STRAY).read_text() == "mine\n"
    assert (habitat.tree / LOCK).exists()
