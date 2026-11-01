"""`open_pr` reads the forge's state of a pull request the unit already records.

Only an open pull request is put in review. A merged or closed one ends the run with the
outcome saying which, and records nothing: the run holds the branch's lock, which the
handlers need, so the caller records it once the lock is released (see
`test_pr_reconcile_lost_merge`).
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING, Unit
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder

UNIT = "add-marker/1"
PR = 7
MERGE_COMMIT = "9f2c1ab04d"


def open_with(
    tmp_path: Path, shows: str | Exception, merge_commit: str | Exception | None = MERGE_COMMIT
) -> tuple[Recorder, RunOutcome, list[tuple[str, int]]]:
    """Run the unit to `open_pr` with PR 7 recorded, the forge answering `shows`."""
    recorder = fresh(tmp_path)
    recorder.store.set_state(UNIT, RUNNING, pr=PR, branch=f"spec/{UNIT}")
    asked: list[tuple[str, int]] = []

    def forge_state(unit: Unit, pr: int) -> str:
        asked.append((unit.id, pr))
        if isinstance(shows, Exception):
            raise shows
        return shows

    def read_merge_commit(unit: Unit, pr: int) -> str | None:
        if isinstance(merge_commit, Exception):
            raise merge_commit
        return merge_commit

    outcome = tick(tmp_path, recorder, forge_state=forge_state, merge_commit=read_merge_commit)
    return recorder, outcome, asked


def test_a_merged_pull_request_ends_the_run_and_is_not_put_in_review(tmp_path: Path) -> None:
    recorder, outcome, _ = open_with(tmp_path, "merged")

    assert outcome.pr_over == "merged"
    assert outcome.pr == PR
    assert recorder.store.get(UNIT).state == RUNNING, "recorded by the caller, not the run"
    assert not any("in review" in line for line in recorder.logged), recorder.logged


def test_a_merged_pull_request_says_the_pushed_commit_and_the_merge_commit(tmp_path: Path) -> None:
    recorder, _, _ = open_with(tmp_path, "merged")

    (line,) = [line for line in recorder.logged if "PR #7 merged on the forge" in line]
    assert "pushed commit sha-" in line
    assert f"merge commit {MERGE_COMMIT[:9]}" in line


def test_a_merge_commit_that_cannot_be_read_is_said_unknown_and_the_path_goes_on(
    tmp_path: Path,
) -> None:
    for unread in (None, RuntimeError("host down")):
        recorder, outcome, _ = open_with(tmp_path / str(unread), "merged", merge_commit=unread)

        assert outcome.pr_over == "merged"
        assert any("merge commit unknown" in line for line in recorder.logged), recorder.logged


def test_a_closed_pull_request_ends_the_run_and_is_not_put_in_review(tmp_path: Path) -> None:
    recorder, outcome, _ = open_with(tmp_path, "closed")

    assert outcome.pr_over == "closed"
    assert recorder.store.get(UNIT).state == RUNNING
    assert not any("in review" in line for line in recorder.logged), recorder.logged


def test_an_open_pull_request_is_put_in_review_after_the_forge_is_asked(tmp_path: Path) -> None:
    recorder, outcome, asked = open_with(tmp_path, "open")

    assert asked == [(UNIT, PR)], "the forge was asked about the recorded pull request"
    assert outcome.pr_over == ""
    assert recorder.store.get(UNIT).state == IN_REVIEW
    assert f"open_pr: in review: PR #{PR}" in recorder.logged


def test_a_forge_that_cannot_answer_costs_nothing_and_the_unit_goes_to_review(
    tmp_path: Path,
) -> None:
    recorder, outcome, _ = open_with(tmp_path, LookupError("the forge does not list PR #7"))

    assert outcome.pr_over == ""
    assert recorder.store.get(UNIT).state == IN_REVIEW
    assert any("could not read the state of PR #7" in line for line in recorder.logged)
