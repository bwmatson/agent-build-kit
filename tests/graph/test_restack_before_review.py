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
from agent_build_kit.pipeline.stack_runner import Restacked
from tests.graph.test_build_path import build, restacked
from tests.graph.test_remaining_paths import fresh
from tests.moved_base_fakes import Profile, moved, restack_lines
from tests.pipeline.test_moved_base_lite import BASE, is_changelog_check, retested
from tests.runner_fakes import Recorder

MOVED = "rebased-sha"
OLD_BASE = "old-base-sha"


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


def test_a_move_before_the_review_that_conflicts_twice_is_held_with_a_note_about_the_review(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)

    def refuses(**kw: Any) -> None:
        if kw.get("resolve") is False:
            raise RuntimeError("both sides changed a.py")

    outcome = build(tmp_path, recorder, restack_onto=refuses)

    assert outcome.status == "held"
    note = recorder.store.get("add-marker/1").note
    assert "before its review" in note and "before its push" not in note, note


class Selects(Profile):
    """The profile's lint and tests, a selected run named `affected`, and no repo checks."""

    def affected_test_commands(self, repo: Path, changed_files: list[str], *a: Any, **kw: Any):
        return [["affected"]]

    def extra_checks(self, repo: Any) -> list[list[str]]:
        return []


class GivesUp(Profile):
    """The profile's lint, tests and repo checks, and no way to say which tests a file affects."""

    def affected_test_commands(self, repo: Path, changed_files: list[str], *a: Any, **kw: Any):
        return None


class CannotSelect(GivesUp):
    """The same, with no repo checks."""

    def extra_checks(self, repo: Any) -> list[list[str]]:
        return []


def test_a_clean_move_before_the_pull_request_over_a_shared_file_runs_no_test_command(
    tmp_path: Path, workspace: Installation
) -> None:
    repo, left = moved(
        tmp_path, own={"a.py": "a = 1\nx = 2\n"}, incoming={"a.py": "w = 0\na = 1\n"}
    )

    passed, output, ran, _ = retested(repo, left, GivesUp(), point="before_pr")

    assert passed, output
    assert ["tests"] not in ran, "the full suite did not start"


def test_a_re_test_before_the_pull_request_in_which_no_command_ran_is_recorded_as_none(
    tmp_path: Path, workspace: Installation
) -> None:
    repo, left = moved(tmp_path, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"})

    passed, output, ran, _ = retested(repo, left, CannotSelect(), point="before_pr")

    assert passed, output
    assert ran == [], "nothing ran"
    (line,) = restack_lines(workspace)
    assert (line["point"], line["retest"]) == ("before_pr", "none")


def test_a_clean_move_before_the_pull_request_over_disjoint_files_runs_the_selection_only(
    tmp_path: Path, workspace: Installation
) -> None:
    repo, left = moved(tmp_path, own={"a.py": "a = 2\n"}, incoming={"b.py": "b = 2\n"})

    passed, output, ran, _ = retested(repo, left, Selects(), point="before_pr")

    assert passed, output
    assert ["affected"] in ran, "the scoped selection ran"
    assert ["tests"] not in ran, "the full suite did not start"
    (line,) = restack_lines(workspace)
    assert (line["point"], line["retest"]) == ("before_pr", "scoped")


def test_a_move_before_the_pull_request_no_selection_can_scope_runs_the_repo_checks_as_lite(
    tmp_path: Path, workspace: Installation
) -> None:
    repo, left = moved(
        tmp_path,
        base=BASE,
        own={"a.py": "a = 2\n"},
        incoming={"c.py": "c = 2\n"},
    )

    passed, output, ran, _ = retested(repo, left, GivesUp(), point="before_pr")

    assert passed, output
    assert [c for c in ran if is_changelog_check(c)], "the repo's own check ran"
    assert ["tests"] not in ran, "the full suite did not start"
    (line,) = restack_lines(workspace)
    assert (line["point"], line["retest"]) == ("before_pr", "lite")
