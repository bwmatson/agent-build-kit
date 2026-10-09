"""A cancelled check is re-run by the runner, not reworked by an agent.

A host that cancels jobs before they start has said nothing about the commit,
so the poller reports them as their own event and the handler asks the host to
run them again, a bounded number of times per head commit.
"""

from functools import partial
from pathlib import Path

import pytest

from agent_build_kit.config import LimitsConfig
from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.base import cancelled_names
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.pr_poller import Poller
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, SATISFIED, UnitState
from tests.check_lists import cancelled_list, failed_list
from tests.factories import stored_unit as unit


def pr(number: int = 4, **overrides) -> PullRequest:
    defaults: dict = {
        "number": number,
        "head": "spec/add-marker/1",
        "base": "main",
        "state": "open",
    }
    return PullRequest(**{**defaults, **overrides})


class Pages:
    """One page of pull requests per poll, the last repeating."""

    def __init__(self, pages: list[list[PullRequest]]) -> None:
        self.pages = pages
        self.calls = 0

    def __call__(self) -> list[PullRequest]:
        page = self.pages[min(self.calls, len(self.pages) - 1)]
        self.calls += 1
        return page


def polled(tmp_path: Path, pages: list[list[PullRequest]]) -> tuple[Poller, list[tuple]]:
    seen: list[tuple] = []
    poller = Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        list_prs=Pages(pages),
        dispatch=lambda action, number, **kw: seen.append((action, number, kw.get("reason"))),
    )
    return poller, seen


def test_the_bound_defaults_to_two_reruns() -> None:
    assert LimitsConfig().max_check_reruns == 2


def test_the_bound_is_not_negative() -> None:
    with pytest.raises(ValueError):
        LimitsConfig(max_check_reruns=-1)


def test_newly_cancelled_checks_are_rerun_and_not_reworked(tmp_path: Path) -> None:
    poller, seen = polled(tmp_path, [[pr()], [pr(checks=cancelled_list("CI"))]])

    poller.poll()
    poller.poll()

    assert [action for action, *_ in seen] == ["rerun_checks"]


def test_checks_already_cancelled_are_not_news(tmp_path: Path) -> None:
    cancelled = pr(checks=cancelled_list("CI"))
    poller, seen = polled(tmp_path, [[pr()], [cancelled], [cancelled]])

    for _ in range(3):
        poller.poll()

    assert [action for action, *_ in seen] == ["rerun_checks"]


def test_checks_cancelled_again_after_a_rerun_are_reported_again(tmp_path: Path) -> None:
    """The rerun makes them run, so they leave the list, and being cancelled
    again is a change - which is what lets the handler count to its bound."""
    cancelled = pr(checks=cancelled_list("CI"))
    poller, seen = polled(tmp_path, [[pr()], [cancelled], [pr()], [cancelled]])

    for _ in range(4):
        poller.poll()

    assert [action for action, *_ in seen] == ["rerun_checks", "rerun_checks"]


def test_a_mixed_outcome_is_reworked_and_rerun(tmp_path: Path) -> None:
    mixed = pr(checks=failed_list("lint") + cancelled_list("CI"))
    poller, seen = polled(tmp_path, [[pr()], [mixed]])

    poller.poll()
    poller.poll()

    assert sorted(action for action, *_ in seen) == ["rerun_checks", "rework"]
    [(_, _, reason)] = [event for event in seen if event[0] == "rework"]
    assert reason == "failing checks: lint", "the cancelled check is not named as a failure"


def test_a_pull_request_met_already_cancelled_is_rerun(tmp_path: Path) -> None:
    """CI usually finishes after the poll has first seen the pull request."""
    poller, seen = polled(tmp_path, [[], [pr(checks=cancelled_list("CI"))]])

    poller.poll()
    poller.poll()

    assert [action for action, *_ in seen] == ["rerun_checks"]


# --- the handler ---------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", IN_REVIEW, pr=4, branch="spec/add-marker/1")
    store.record_push("add-marker/1", "aaa1111")
    return store


class Reruns:
    def __init__(self) -> None:
        self.pulls: list[PullRequest] = []

    def __call__(self, pull: PullRequest) -> None:
        self.pulls.append(pull)


def handle(store: UnitStore, reruns: Reruns, log: list[str], number: int = 4) -> bool:
    return events.on_rerun_checks(
        number,
        repo="app",
        pull=pr(number, checks=cancelled_list("CI")),
        store=store,
        rerun=reruns,
        log=log.append,
    )


def test_the_handler_asks_the_forge_to_rerun_the_cancelled_checks(store: UnitStore) -> None:
    reruns: Reruns = Reruns()
    log: list[str] = []

    assert handle(store, reruns, log) is True

    assert [cancelled_names(pull.checks) for pull in reruns.pulls] == [("CI",)]
    assert any("aaa1111" in line and "re-run 1 of 2" in line for line in log)


def test_the_handler_stops_at_the_bound_and_says_why(store: UnitStore) -> None:
    reruns: Reruns = Reruns()
    log: list[str] = []

    for _ in range(4):
        handle(store, reruns, log)

    assert len(reruns.pulls) == 2
    assert any("re-run 2 of 2" in line for line in log)
    assert any("keeps cancelling the checks" in line for line in log)


def test_a_spent_bound_does_not_rework_or_hold_the_unit(store: UnitStore) -> None:
    reruns: Reruns = Reruns()

    for _ in range(3):
        handle(store, reruns, [])

    stored = store.get("add-marker/1")
    assert stored.state == IN_REVIEW
    assert stored.feedback == ""


def test_the_count_starts_again_when_the_head_moves(store: UnitStore) -> None:
    reruns: Reruns = Reruns()
    log: list[str] = []
    for _ in range(3):
        handle(store, reruns, log)
    assert len(reruns.pulls) == 2

    store.record_push("add-marker/1", "bbb2222")
    handle(store, reruns, log)

    assert len(reruns.pulls) == 3
    assert any("bbb2222" in line and "re-run 1 of 2" in line for line in log)


def test_the_count_survives_the_process(store: UnitStore, tmp_path: Path) -> None:
    """Each poll is a fresh process; the count is on the stored unit."""
    reruns: Reruns = Reruns()
    handle(store, reruns, [])
    handle(UnitStore(tmp_path / "units.json"), reruns, [])
    handle(UnitStore(tmp_path / "units.json"), reruns, [])

    assert len(reruns.pulls) == 2


def test_a_unit_stored_before_the_count_existed_loads_and_is_rerun(tmp_path: Path) -> None:
    path = tmp_path / "units.json"
    older = UnitStore(path)
    older.upsert([unit("add-marker/1")])
    older.set_state("add-marker/1", IN_REVIEW, pr=4, branch="spec/add-marker/1")
    reruns: Reruns = Reruns()

    handle(UnitStore(path), reruns, [])

    assert len(reruns.pulls) == 1


@pytest.mark.parametrize("state", [HELD, SATISFIED])
def test_a_held_or_satisfied_unit_keeps_its_checks(store: UnitStore, state: UnitState) -> None:
    store.set_state("add-marker/1", state)
    reruns: Reruns = Reruns()
    log: list[str] = []

    assert handle(store, reruns, log) is True

    assert reruns.pulls == []
    assert store.get("add-marker/1").check_reruns == 0
    assert any(f"is {state}, leaving the checks" in line for line in log)


def test_a_refused_rerun_is_logged_and_not_counted(store: UnitStore) -> None:
    log: list[str] = []

    def refuse(pull: PullRequest) -> None:
        raise RuntimeError("no actions: write")

    taken = events.on_rerun_checks(
        4,
        repo="app",
        pull=pr(checks=cancelled_list("CI")),
        store=store,
        rerun=refuse,
        log=log.append,
    )

    assert taken is True
    assert store.get("add-marker/1").check_reruns == 0
    assert any("the host refused: no actions: write" in line for line in log)


def test_an_unknown_pull_request_is_ignored(store: UnitStore) -> None:
    reruns: Reruns = Reruns()

    assert handle(store, reruns, [], number=99) is True

    assert reruns.pulls == []


def test_the_dispatch_routes_the_event_to_the_forge(store: UnitStore) -> None:
    asked: list[tuple[str, PullRequest]] = []
    logged: list[str] = []
    dispatch = events.build_dispatch(
        store,
        restack=lambda **kw: None,
        rerun_checks=lambda repo, pull: asked.append((repo, pull)),
        log=logged.append,
    )

    taken = partial(dispatch, repo="app")("rerun_checks", 4, pull=pr(checks=cancelled_list("CI")))

    assert taken is True
    assert [repo for repo, _ in asked] == ["app"]
    assert not any("unhandled" in line for line in logged)
