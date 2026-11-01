"""The tick runs the reconcile pass beside the poll, with the lane the poll's handlers get.

The scene is the pass's own: a unit in review whose pull request the poller's cache shows
merged, and a child stacked on it. Nothing is polled, so only the pass can record the merge.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline.pr_poller import PrState, snapshot, state_path
from agent_build_kit.pipeline.units import IN_REVIEW, SETTLING
from tests.factories import stored_unit
from tests.tick_driver import OTHER, UNIT, Setup, make_setup

PR = 7


@pytest.fixture
def graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    setup = make_setup(tmp_path, monkeypatch)
    setup.store.upsert([stored_unit(OTHER, depends_on=(UNIT,))])
    setup.store.set_state(UNIT, IN_REVIEW, pr=PR, branch=f"spec/{UNIT}")
    setup.store.set_state(OTHER, IN_REVIEW, pr=PR + 1, branch=f"spec/{OTHER}")
    pull = PullRequest(number=PR, head=f"spec/{UNIT}", base="main", state="merged")
    PrState.save(state_path(setup.inst.state_dir, "app"), {str(PR): snapshot(pull)}, "app")
    return setup


def test_a_tick_records_the_merge_the_cache_shows_and_hands_the_child_to_the_lane(
    graph: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    moved_on: list[bool] = []

    def restack(**kwargs):
        def move(**moved):
            moved_on.append(threading.current_thread() is threading.main_thread())

        return move

    monkeypatch.setattr(cli, "build_restack", restack)

    assert graph.tick() == 0

    assert graph.store.get(UNIT).state == SETTLING
    assert moved_on, "the child was restacked"
    assert not any(moved_on), "in the lane's worker, not inline in the tick"


def test_a_pass_that_raises_is_said_and_the_tick_goes_on(
    graph: Setup, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(**kwargs):
        raise RuntimeError("cache unreadable")

    after: list[bool] = []
    monkeypatch.setattr(cli, "reconcile", broken)
    monkeypatch.setattr(cli, "retry_closes", lambda *args, **kwargs: after.append(True))

    assert graph.tick() == 0

    assert "reconcile skipped — RuntimeError: cache unreadable" in capsys.readouterr().out
    assert graph.store.get(UNIT).state == IN_REVIEW
    assert after, "the round went on to its next step"
