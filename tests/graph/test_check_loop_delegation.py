"""The four check-loop nodes delegate to the one shared routine (spec: one-check-and-fix-loop).

The routine is replaced by a recording fake that runs the loop's own check and answers from a
script, so what is asserted is what each node hands over, and that the node does none of the
routine's steps itself.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph import check_loop
from agent_build_kit.graph.check_loop import CheckLoop
from agent_build_kit.graph.nodes import BuildPath
from agent_build_kit.graph.state import UnitRun
from agent_build_kit.pipeline.stack_runner import UNIT_TEST_FAILED
from agent_build_kit.pipeline.unit_store import FeedbackSource
from tests.factories import unit
from tests.graph.stub_loop_fakes import StubLoop, feedback_writes, stubbed_build
from tests.graph_driver import fresh as fresh_store
from tests.runner_fakes import make_runner


class FakeRoutine:
    """Stands in for `check_round` and `fix_round`: records each call with the loop it was given,
    runs the loop's check, and answers the check of a loop from `passes` in order, a failure
    (`{}`) for each `False`."""

    def __init__(self, passes: dict[str, list[bool]]) -> None:
        self.passes = passes
        self.checked: list[CheckLoop] = []
        self.fixed: list[CheckLoop] = []
        self.check_answers: list[tuple[bool, str]] = []

    def check_round(self, nodes: BuildPath, state: UnitRun, loop: CheckLoop) -> dict[str, Any]:
        self.checked.append(loop)
        self.check_answers.append(loop.check())
        answers = self.passes[loop.rounds]
        return (
            {"ok": True} if answers[min(len(self.checked_in(loop)) - 1, len(answers) - 1)] else {}
        )

    def fix_round(self, nodes: BuildPath, state: UnitRun, loop: CheckLoop) -> dict[str, Any]:
        self.fixed.append(loop)
        return {loop.rounds: len(self.fixes_in(loop))}

    def checked_in(self, loop: CheckLoop) -> list[CheckLoop]:
        return [seen for seen in self.checked if seen.rounds == loop.rounds]

    def fixes_in(self, loop: CheckLoop) -> list[CheckLoop]:
        return [seen for seen in self.fixed if seen.rounds == loop.rounds]


class Spied(StubLoop):
    """A stubbed-loop recorder that counts the runner's tree-state reads."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.tree_reads = 0

    def tree_state(self, cwd: Path) -> str:
        self.tree_reads += 1
        return super().tree_state(cwd)


def routine_in_place(monkeypatch: pytest.MonkeyPatch, passes: dict[str, list[bool]]) -> FakeRoutine:
    fake = FakeRoutine(passes)
    monkeypatch.setattr(check_loop, "check_round", fake.check_round)
    monkeypatch.setattr(check_loop, "fix_round", fake.fix_round)
    return fake


def path_over(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **options: Any
) -> tuple[BuildPath, Spied, list[tuple[str, FeedbackSource]]]:
    """A build path over a stubbed-loop recorder, and the feedback writes made to its store."""
    stubbed_build()
    recorder = Spied(fresh_store(tmp_path).store, **options)
    saved = feedback_writes(recorder, monkeypatch)
    runner = make_runner(recorder.store, recorder, tmp_path, **recorder.overrides(tmp_path))
    return (
        BuildPath(runner, unit(), base="main", graph=[], run_log=None, tracer=None),
        recorder,
        saved,
    )


def stub_state(**fields: Any) -> UnitRun:
    return UnitRun(unit_id=unit().id, change="add-marker", stub_loop=True, **fields)


def checks_state(**fields: Any) -> UnitRun:
    return UnitRun(unit_id=unit().id, change="add-marker", **fields)


def test_stub_checks_calls_the_routine_once_with_the_static_checks_and_no_commit_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, recorder, _ = path_over(tmp_path, monkeypatch)
    fake = routine_in_place(monkeypatch, {"stub_rounds": [True]})

    path.stub_checks(stub_state())

    (loop,) = fake.checked
    assert loop.commit is None, "the stub loop makes no fix commit"
    assert loop.source is FeedbackSource.STUB_CHECKS
    assert loop.heading == ""
    assert loop.rounds == "stub_rounds"
    assert recorder.events.count("stub-checks") == 1, "the check is the static checks"
    assert "unit-test" not in recorder.events, "and runs no test"


def test_fix_stub_checks_calls_the_routine_once_with_the_same_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _, _ = path_over(tmp_path, monkeypatch)
    fake = routine_in_place(monkeypatch, {"stub_rounds": [True]})

    update = path.fix_stub_checks(stub_state())

    (loop,) = fake.fixed
    assert (loop.commit, loop.source, loop.rounds) == (
        None,
        FeedbackSource.STUB_CHECKS,
        "stub_rounds",
    )
    assert update == {"stub_rounds": 1}, "the routine's update is the node's"


def test_checks_calls_the_routine_once_with_the_unit_test_run_and_the_commit_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, recorder, _ = path_over(tmp_path, monkeypatch)
    fake = routine_in_place(monkeypatch, {"fix_rounds": [True]})

    path.checks(checks_state())

    (loop,) = fake.checked
    assert loop.source is FeedbackSource.UNIT_TEST
    assert loop.heading == UNIT_TEST_FAILED
    assert loop.rounds == "fix_rounds"
    assert loop.commit is not None
    assert loop.commit.format(title="T", n=2) == "fix: T (checks, round 2)"
    assert recorder.events.count("unit-test") == 1, "the check is the unit-test run"
    assert "stub-checks" not in recorder.events


def test_fix_checks_calls_the_routine_once_with_the_same_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _, _ = path_over(tmp_path, monkeypatch)
    fake = routine_in_place(monkeypatch, {"fix_rounds": [True]})

    path.fix_checks(checks_state())

    (loop,) = fake.fixed
    assert loop.source is FeedbackSource.UNIT_TEST
    assert loop.rounds == "fix_rounds"
    assert loop.commit is not None
    assert loop.commit.format(title="T", n=1) == "fix: T (checks, round 1)"


@pytest.mark.parametrize("node", ["stub_checks", "fix_stub_checks", "checks", "fix_checks"])
def test_no_node_repeats_a_step_the_routine_owns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, node: str
) -> None:
    path, recorder, saved = path_over(tmp_path, monkeypatch)
    routine_in_place(monkeypatch, {"stub_rounds": [False], "fix_rounds": [False]})
    state = stub_state() if node.endswith("stub_checks") else checks_state()
    call: Callable[[UnitRun], Any] = getattr(path, node)

    call(state)

    assert recorder.tree_reads == 0, "the digest of a fix round is the routine's"
    assert saved == [], "a failure is saved by the routine"
    assert recorder.fix_prompts == [], "the fix agent is the routine's"
    assert not [event for event in recorder.events if event.startswith("commit:")]
