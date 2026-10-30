"""`open_pr` reads the forge's state of a pull request the unit already records.

Only an open pull request is put in review; a merged one takes the merge path and a
closed one the closed path, the same handlers the poller reports to.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.events import build_dispatch
from agent_build_kit.pipeline.units import CLOSED, IN_REVIEW, RUNNING, SETTLING, Unit
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder

UNIT = "add-marker/1"
PR = 7


class Forge:
    """What `open_pr` was asked, and what it was answered."""

    def __init__(self, recorder: Recorder, shows: str) -> None:
        self.recorder = recorder
        self.shows = shows
        self.asked: list[tuple[str, int]] = []
        self.dispatched: list[tuple[str, int, str]] = []
        self.dispatch = build_dispatch(
            recorder.store,
            restack=lambda **kwargs: None,
            merge_record=lambda unit: ("9f2c1ab", 7),
            log=recorder.log,
        )

    def state(self, unit: Unit, pr: int) -> str:
        self.asked.append((unit.id, pr))
        return self.shows

    def report(self, event: str, number: int, *, repo: str, **kwargs) -> bool:
        self.dispatched.append((event, number, repo))
        return self.dispatch(event, number, repo=repo, **kwargs)


def open_with(tmp_path: Path, shows: str) -> tuple[Recorder, Forge]:
    recorder = fresh(tmp_path)
    recorder.store.set_state(UNIT, RUNNING, pr=PR, branch=f"spec/{UNIT}")
    forge = Forge(recorder, shows)
    tick(tmp_path, recorder, forge_state=forge.state, dispatch=forge.report)
    return recorder, forge


def test_a_merged_pull_request_takes_the_merge_path(tmp_path: Path) -> None:
    recorder, forge = open_with(tmp_path, "merged")

    assert forge.dispatched == [("merged", PR, "app")]
    assert recorder.store.get(UNIT).state == SETTLING
    assert not any("in review" in line for line in recorder.logged), recorder.logged


def test_a_closed_pull_request_takes_the_closed_path(tmp_path: Path) -> None:
    recorder, forge = open_with(tmp_path, "closed")

    assert forge.dispatched == [("closed", PR, "app")]
    assert recorder.store.get(UNIT).state == CLOSED
    assert not any("in review" in line for line in recorder.logged), recorder.logged


def test_an_open_pull_request_is_put_in_review_after_the_forge_is_asked(tmp_path: Path) -> None:
    recorder, forge = open_with(tmp_path, "open")

    assert forge.asked == [(UNIT, PR)], "the forge was asked about the recorded pull request"
    assert forge.dispatched == []
    assert recorder.store.get(UNIT).state == IN_REVIEW
    assert f"in review: PR #{PR}" in recorder.logged
