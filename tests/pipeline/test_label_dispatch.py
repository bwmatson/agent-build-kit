"""What the poller does with labels: its own are not instructions, a person's
are, and a rework instruction is consumed when it is acted on.
"""

from functools import partial
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.labels import StateLabels
from agent_build_kit.pipeline.pr_poller import Poller
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED
from agent_build_kit.pipeline.vocabulary import state_label_names
from tests.factories import stored_unit as unit
from tests.forges.stand_in import StandInForge, lookup

PR = 4
REWORK = "agent-rework"
HOLD = "agent-hold"


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", IN_REVIEW, pr=PR, branch="spec/add-marker/1")
    return store


@pytest.fixture
def forge() -> StandInForge:
    return StandInForge(
        prs=[PullRequest(number=PR, head="spec/add-marker/1", base="main", state="open")]
    )


@pytest.fixture
def labels(forge: StandInForge) -> StateLabels:
    return StateLabels(lookup(forge), log=lambda m: None)


@pytest.fixture
def events_seen() -> list[tuple[str, int]]:
    return []


@pytest.fixture
def poller(
    tmp_path: Path,
    store: UnitStore,
    forge: StandInForge,
    labels: StateLabels,
    events_seen: list[tuple[str, int]],
) -> Poller:
    handle = events.build_dispatch(store, restack=lambda **_: None, log=lambda m: None)

    def dispatch(event: str, number: int, **kwargs) -> bool:
        events_seen.append((event, number))
        return handle(event, number, repo="app", **kwargs)

    return Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        list_prs=partial(forge.list_prs, forge.repo_id()),
        dispatch=dispatch,
        consume=lambda number, name: labels.consume("app", number, name),
    )


def test_a_label_the_pipeline_writes_dispatches_nothing(
    poller: Poller, labels: StateLabels, events_seen: list
) -> None:
    poller.poll()

    names = state_label_names()
    assert names
    for name in sorted(names):
        labels.set_state("app", PR, name)
        poller.poll()

    assert events_seen == []


def test_every_state_label_at_once_is_left_alone_by_the_poller(
    poller: Poller, forge: StandInForge, events_seen: list
) -> None:
    poller.poll()
    names = state_label_names()
    assert names
    forge.on_pr[PR] = set(names)

    poller.poll()

    assert events_seen == []


def test_a_label_a_person_writes_still_dispatches(
    poller: Poller, forge: StandInForge, events_seen: list
) -> None:
    poller.poll()
    forge.on_pr[PR] = {HOLD}

    poller.poll()

    assert events_seen == [("hold", PR)]


def test_a_rework_asked_for_by_label_removes_that_label(
    poller: Poller, forge: StandInForge, store: UnitStore
) -> None:
    poller.poll()
    forge.on_pr[PR] = {REWORK}

    poller.poll()

    assert store.get("add-marker/1").state == PLANNED
    assert REWORK not in forge.on_pr[PR]


def test_the_same_rework_can_be_asked_for_again(
    poller: Poller, forge: StandInForge, store: UnitStore, events_seen: list
) -> None:
    poller.poll()
    forge.on_pr[PR] = {REWORK}
    poller.poll()
    store.set_state("add-marker/1", IN_REVIEW)
    forge.on_pr[PR].add(REWORK)  # added again, with no poll in between

    poller.poll()

    assert [event for event, _ in events_seen] == ["rework", "rework"]
    assert store.get("add-marker/1").state == PLANNED


def test_a_hold_label_is_left_in_place(
    poller: Poller, forge: StandInForge, store: UnitStore
) -> None:
    poller.poll()
    forge.on_pr[PR] = {HOLD}

    poller.poll()

    assert store.get("add-marker/1").state == HELD
    assert HOLD in forge.on_pr[PR]


def test_a_rework_a_review_asked_for_leaves_other_labels_alone(
    store: UnitStore, forge: StandInForge, labels: StateLabels
) -> None:
    forge.on_pr[PR] = {HOLD}
    dispatch = events.build_dispatch(store, restack=lambda **_: None, log=lambda m: None)

    dispatch("rework", PR, repo="app", reason="new comment")

    assert HOLD in forge.on_pr[PR]


@pytest.mark.parametrize("wired", [False, True], ids=["cannot remove", "removal refused"])
def test_a_rework_label_that_stays_on_the_pull_request_reworks_the_unit_once(
    tmp_path: Path, store: UnitStore, wired: bool
) -> None:
    forge = StandInForge(
        prs=[PullRequest(number=PR, head="spec/add-marker/1", base="main", state="open")],
        label_errors=("remove",),
    )
    handle = events.build_dispatch(store, restack=lambda **_: None, log=lambda m: None)
    seen: list[str] = []

    def dispatch(event: str, number: int, **kwargs) -> bool:
        seen.append(event)
        return handle(event, number, repo="app", **kwargs)

    labels = StateLabels(lookup(forge), log=lambda m: None)

    def consume(number: int, name: str) -> bool:
        return labels.consume("app", number, name) if wired else False

    poller = Poller(
        repo="app",
        state_path=tmp_path / "poll.json",
        list_prs=partial(forge.list_prs, forge.repo_id()),
        dispatch=dispatch,
        consume=consume,
    )
    poller.poll()
    forge.on_pr[PR] = {REWORK}

    poller.poll()
    store.set_state("add-marker/1", IN_REVIEW)
    poller.poll()
    poller.poll()

    assert seen == ["rework"]
    requeues = [e for e in store.history("add-marker/1") if e.get("note", "").startswith("rework")]
    assert len(requeues) == 1
