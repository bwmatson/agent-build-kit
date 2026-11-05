"""A unit is restacked and re-tested after its checks pass and before the review agent reads
it, and a clean move before the push never starts a full suite (spec: restack-points, a unit
is restacked before its review and before its pull request).

`restack_onto` is faked at its edge, as in the build path's tests; the stage a call belongs to
is read from what the recorder has seen so far.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.stack_runner import Restacked
from agent_build_kit.pipeline.wiring import build_unit_test
from tests.conftest import make_installation
from tests.graph.test_build_path import build, restacked
from tests.graph.test_remaining_paths import fresh
from tests.moved_base_fakes import Profile, moved, passing, restack_lines
from tests.runner_fakes import Recorder

MOVED = "rebased-sha"
OLD_BASE = "old-base-sha"
LINE = "moved base:"


class Stages:
    """A restack that answers by the stage the run is at: `prepare` before any check has run,
    `before_review` after the checks and before the review, `before_pr` after the review.
    `answers` maps a stage to its result; a stage not in it, or asked a second time, finds the
    base unmoved. A move that
    is not resolved puts the branch at `MOVED`."""

    def __init__(self, recorder: Recorder, **answers: Restacked) -> None:
        self.recorder = recorder
        self.answers = answers
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.moved = False

    def stage(self) -> str:
        events = self.recorder.events
        if "review" in events:
            return "before_pr"
        return "before_review" if "unit-test" in events else "prepare"

    def head(self, cwd: Path) -> str:
        return MOVED if self.moved else self.recorder.head(cwd)

    def restack(self, **kw: Any) -> Restacked | None:
        stage = self.stage()
        self.calls.append((stage, kw))
        result = self.answers.pop(stage, None)
        if result is None:
            return None
        self.moved = not (result.conflict or result.resolved)
        self.recorder.events.append(f"moved:{stage}")
        return result

    def overrides(self) -> dict[str, Any]:
        return {"head": self.head, "restack_onto": self.restack}

    def stages(self) -> list[str]:
        return [stage for stage, _ in self.calls]


def test_a_unit_whose_base_moved_after_the_checks_is_restacked_and_re_tested_before_the_review(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    stages = Stages(recorder, before_review=restacked(old_base=OLD_BASE))

    outcome = build(tmp_path, recorder, **stages.overrides())

    assert outcome.status == "open"
    events = recorder.events
    assert events.index("unit-test") < events.index("moved:before_review")
    after = events[events.index("moved:before_review") :]
    assert after.index("unit-test") < after.index("review"), "re-tested before the review"
    assert events.count("unit-test") == 2
    assert events.count("review") == 1, "the move spends no review round"
    assert recorder.unit_test_moved_from == [None, OLD_BASE]


def test_the_review_agent_reads_the_rebased_head(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    stages = Stages(recorder, before_review=restacked())
    seen: list[str] = []

    def review(**kw: Any) -> str:
        seen.append(stages.head(kw["cwd"]))
        return recorder.review(**kw)

    build(tmp_path, recorder, run_review=review, **stages.overrides())

    assert seen == [MOVED]


def test_a_base_that_has_not_moved_is_asked_after_the_checks_and_adds_no_re_test(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    stages = Stages(recorder)

    outcome = build(tmp_path, recorder, **stages.overrides())

    assert outcome.status == "open"
    assert "before_review" in stages.stages(), "the base is asked after the checks"
    assert recorder.events.count("unit-test") == 1
    assert recorder.events.count("review") == 1


def test_a_conflict_before_the_review_goes_to_resolution_and_not_to_the_review(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    stages = Stages(
        recorder,
        before_review=restacked(old_base=OLD_BASE, conflict="CONFLICT in a.py"),
    )

    build(tmp_path, recorder, **stages.overrides())

    events = recorder.events
    assert events.index("moved:before_review") < events.index("review")
    assert events.count("review") == 1, "read once, after the resolution"
    assert stages.stages()[:2] == ["before_review", "before_review"], "asked again, to resolve"
    assert stages.calls[1][1].get("resolver"), "the second call has the resolver"


def test_a_move_before_the_review_is_recorded_as_before_review(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    stages = Stages(recorder, before_review=restacked(old_base=OLD_BASE))

    build(tmp_path, recorder, **stages.overrides())

    (line,) = [line for line in restack_lines(workspace) if line["point"] == "before_review"]
    assert (line["moved"], line["moved_from"], line["outcome"]) == (True, OLD_BASE, "clean")


def test_a_clean_move_before_the_pull_request_that_shares_a_code_file_never_runs_the_full_suite(
    tmp_path: Path,
) -> None:
    make_installation(tmp_path / "planning", limits={"unit_test_repeat_runs": 0})
    repo, left = moved(
        tmp_path, own={"a.py": "a = 1\nx = 2\n"}, incoming={"a.py": "w = 0\na = 1\n"}
    )
    logged: list[str] = []
    unit_test = build_unit_test(profile=Profile(), run=passing, log=logged.append)

    token = spans.restack_point.set("before_pr")
    try:
        ok, _ = unit_test(cwd=repo, base="main", moved_from=left)
    finally:
        spans.restack_point.reset(token)

    assert ok
    found = [line for line in logged if LINE in line]
    assert len(found) == 1
    assert "full suite" not in found[0], found[0]
