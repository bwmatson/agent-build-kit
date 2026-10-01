"""A node re-run after a kill does nothing it already did (docs/unit-graph.md,
Durability): the thread resumes at the node the process died in, and the node
checks git, the remote and the forge before it acts.

The process dies right after a step's side effect and before the node returns,
the worst place: the work is done and nothing but the world remembers it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.unit import run_unit
from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.factories import unit
from tests.runner_fakes import Killed, Recorder, make_runner, rejecting


def drive(tmp_path: Path, recorder: Recorder) -> RunOutcome:
    runner = make_runner(recorder.store, recorder, tmp_path)

    async def go() -> RunOutcome:
        # A new connection each time, as a new process has.
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            return await run_unit(
                runner, recorder.store.get(unit().id), base="main", graph=[], saver=saver
            )

    return asyncio.run(go())


@pytest.mark.parametrize("killed_after", ["commit:test", "commit:feat", "push", "pr"])
def test_a_node_killed_after_its_effect_does_not_repeat_it_when_resumed(
    tmp_path: Path, killed_after: str
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(store, kill_after=killed_after)

    with pytest.raises(Killed):
        drive(tmp_path, recorder)
    outcome = drive(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.made == 2, "one tests commit and one implementation commit, no more"
    assert recorder.events.count("claude:tests") == 1
    assert recorder.events.count("claude:impl") == 1
    assert recorder.remote == ["sha-2"]
    assert outcome.pr == 7
    assert recorder.store.get(unit().id).pr == 7
    assert recorder.store.get(unit().id).state == IN_REVIEW
    assert len(recorder.prs) == 1, "the pull request is found, not opened again"


def test_a_rework_killed_after_its_commit_is_not_made_again_when_resumed(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(store, kill_after="commit:fix")
    recorder.verdicts = [rejecting("rename it")]

    with pytest.raises(Killed):
        drive(tmp_path, recorder)
    outcome = drive(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.events.count("claude:rework") == 1
    assert recorder.events.count("commit:fix") == 1


def test_a_check_fix_killed_after_its_commit_is_not_made_again_when_resumed(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    recorder = Recorder(store, kill_after="commit:fix")
    recorder.tier1_results = [(False, "ERROR implicit-any"), (True, "")]

    with pytest.raises(Killed):
        drive(tmp_path, recorder)
    outcome = drive(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.events.count("claude:fix_checks") == 1
    assert recorder.made == 3, "tests, implementation and the one fix"
