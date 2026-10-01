"""The classic runner's build-path scenarios, run through the graph engine
with the same injected fakes (docs/unit-graph.md, Testing): each reaches the
same outcome, state, pull request and commits as `UnitRunner.run`."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.unit import run_unit
from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, branch_name
from tests.factories import stored_unit, unit
from tests.runner_fakes import Recorder, make_runner, rejecting


def build(
    tmp_path: Path, recorder: Recorder, *, graph: list[StoredUnit] | None = None
) -> RunOutcome:
    runner = make_runner(recorder.store, recorder, tmp_path)

    async def go() -> RunOutcome:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            return await run_unit(
                runner,
                recorder.store.get(unit().id),
                base="main",
                graph=graph or [],
                saver=saver,
            )

    return asyncio.run(go())


def fresh(tmp_path: Path, **options) -> Recorder:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    return Recorder(store, **options)


def test_a_unit_runs_tests_first_then_implementation(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)

    build(tmp_path, recorder)

    assert recorder.events[:4] == ["claude:tests", "commit:test", "claude:impl", "commit:feat"]


def test_an_approved_build_is_pushed_and_opened_and_recorded_as_in_review(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert outcome.pr == 7
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.pr, stored.branch) == (IN_REVIEW, 7, "spec/add-marker/1")
    assert recorder.events.count("review") == 1
    assert "claude:rework" not in recorder.events
    assert recorder.events.index("push") < recorder.events.index("pr")
    assert recorder.events.index("push") < recorder.events.index("status")


def test_the_checks_run_once_and_before_the_review_and_the_review_before_the_push(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)

    build(tmp_path, recorder)

    assert recorder.events.count("tier1") == 1
    assert recorder.events.index("tier1") < recorder.events.index("review")
    assert recorder.events.index("review") < recorder.events.index("push")


def test_a_rejected_build_is_sent_back_with_the_findings_and_reviewed_again(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("the session registry leaks")]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.events.count("review") == 2
    assert "claude:rework" in recorder.events
    assert "leaks" in " ".join(recorder.prompts)


def test_an_implementation_that_adds_nothing_still_goes_to_review(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, commits_from_impl=0)

    outcome = build(tmp_path, recorder)

    assert "review" in recorder.events
    assert outcome.status == "open"


def test_only_the_approved_commit_is_pushed(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)

    build(tmp_path, recorder)

    assert recorder.remote == [recorder.head(tmp_path)]
    assert recorder.store.get(unit().id).approved == recorder.head(tmp_path)


def test_a_failing_tier_one_fails_the_unit_and_leaves_no_pull_request(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, tier1_ok=False)
    recorder.tier1_output = "E   ImportError: cannot import name 'geo' from 'src'"

    outcome = build(tmp_path, recorder)

    assert outcome.status == "failed"
    assert recorder.store.get(unit().id).state == "failed"
    assert "ImportError" in recorder.store.get(unit().id).feedback
    assert "push" not in recorder.events
    assert recorder.prs == {}


def test_the_prompts_are_scoped_to_this_unit_and_name_the_change(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    graph = [
        stored_unit("add-marker/1", groups=(1,)),
        stored_unit("add-marker/2", groups=(2, 3), depends_on=("add-marker/1",)),
    ]

    build(tmp_path, recorder, graph=graph)

    assert len(recorder.prompts) == 2, "the tests and the implementation, nothing else"
    for prompt in recorder.prompts:
        assert "/opsx:" not in prompt
        assert "openspec/changes/add-marker" in prompt
        assert "2, 3" in prompt, "the later unit's groups are named"
        assert "later" in prompt.lower()


def test_a_unit_with_feedback_addresses_it_instead_of_starting_over(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    recorder.store.set_state(unit().id, IN_REVIEW, pr=4, branch=branch_name(unit()))
    recorder.store.set_feedback(unit().id, "Use a Sequence, list is invariant")

    build(tmp_path, recorder)

    assert len(recorder.prompts) == 1, "one rework, not the tests-then-implementation pair"
    assert "Use a Sequence, list is invariant" in recorder.prompts[0]
    assert recorder.store.get(unit().id).feedback == "", "cleared once addressed"


def test_a_unit_with_work_on_its_branch_and_no_feedback_builds_nothing_more(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, commits_from_impl=0)
    recorder.made = 2

    outcome = build(tmp_path, recorder)

    assert recorder.prompts == [], "no model call at all"
    assert "tier1" in recorder.events
    assert outcome.status == "open"
