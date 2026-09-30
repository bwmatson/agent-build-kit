"""A unit's state, on its pull request.

Labelling is cosmetic: one state label at a time, the graph's words, and no
failure of it is ever a unit's problem. The forge is a stand-in that records
which labels each pull request carries.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.labels import StateLabels
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.pipeline.vocabulary import STATES, change_label, state_label_names
from tests.factories import stored_unit as unit
from tests.forges.stand_in import StandInForge, lookup

PR = 7


def on_pr(forge: StandInForge) -> set[str]:
    return forge.on_pr.get(PR, set())


def state_labels_on(forge: StandInForge) -> set[str]:
    return on_pr(forge) & state_label_names()


@pytest.fixture
def forge() -> StandInForge:
    return StandInForge()


@pytest.fixture
def logged() -> list[str]:
    return []


@pytest.fixture
def labels(forge: StandInForge, logged: list[str]) -> StateLabels:
    return StateLabels(lookup(forge), log=logged.append)


def test_a_pull_request_carries_one_state_label_as_its_unit_moves(
    forge: StandInForge, labels: StateLabels
) -> None:
    for state in ("running", "in_review", "paused_rework", "held"):
        labels.set_state("app", PR, state)

        assert state_labels_on(forge) == {STATES[state].name}, f"after {state}"


def test_merging_or_closing_adds_no_state_label(forge: StandInForge, labels: StateLabels) -> None:
    labels.set_state("app", PR, "in_review")

    for state in ("merged", "closed"):
        labels.set_state("app", PR, state)

        assert state_labels_on(forge) <= {"in-review"}, state
        assert STATES[state].name not in on_pr(forge)


def test_a_label_a_person_or_the_change_put_there_survives_a_state_change(
    forge: StandInForge, labels: StateLabels
) -> None:
    forge.on_pr[PR] = {"bug", "agent-hold"}
    labels.tag_change("app", PR, "add-marker")

    labels.set_state("app", PR, "running")
    labels.set_state("app", PR, "in_review")

    assert {"bug", "agent-hold", change_label("add-marker").name} <= on_pr(forge)
    assert state_labels_on(forge) == {"in-review"}


def test_the_change_label_is_stable_and_not_a_state_or_an_instruction() -> None:
    label = change_label("add-marker")

    assert label == change_label("add-marker")
    assert label != change_label("other-change")
    assert label.name not in state_label_names()
    assert not label.name.startswith("agent-")


def test_a_missing_label_is_created_once_with_its_description(
    forge: StandInForge, labels: StateLabels
) -> None:
    labels.set_state("app", PR, "running")
    labels.set_state("app", 8, "running")
    labels.set_state("app", PR, "in_review")
    labels.set_state("app", PR, "running")

    created = [label.name for label in forge.label_creations]
    assert sorted(created) == ["in-review", "running"]
    assert all(label.description for label in forge.label_creations)


@pytest.mark.parametrize("failing", ["set", "add", "remove"])
def test_a_label_call_that_fails_is_logged_once_and_raises_nothing(
    failing: str, logged: list[str]
) -> None:
    forge = StandInForge(label_errors=(failing,))
    labels = StateLabels(lookup(forge), log=logged.append)

    labels.set_state("app", PR, "running")
    labels.tag_change("app", PR, "add-marker")
    labels.consume("app", PR, "agent-rework")

    assert len(logged) == 1, logged


def wired(tmp_path: Path, forge: StandInForge, logged: list[str]) -> UnitStore:
    """A store whose state changes reach the forge, as `cli.store_for` builds it."""
    labels = StateLabels(lookup(forge), log=logged.append)
    return UnitStore(
        tmp_path / "units.json",
        on_state=lambda unit, units, opened: labels.follow(unit, units, opened=opened),
    )


def test_a_failed_label_leaves_the_unit_where_the_rework_put_it(tmp_path: Path) -> None:
    logged: list[str] = []
    store = wired(tmp_path, StandInForge(label_errors=("set", "add", "remove")), logged)
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", IN_REVIEW, pr=PR, branch="spec/add-marker/1")
    dispatch = events.build_dispatch(store, restack=lambda **_: None, log=lambda m: None)

    handled = dispatch("rework", PR, repo="app", reason="agent-rework label")

    assert handled is True
    assert len(logged) >= 1, "the failures are logged, not swallowed silently"
    assert store.get("add-marker/1").state == PLANNED


def test_the_store_decides_not_the_label_on_the_pull_request(tmp_path: Path) -> None:
    """A pull request wearing a stale `held` label does not hold its unit."""
    forge = StandInForge()
    store = wired(tmp_path, forge, [])
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", IN_REVIEW, pr=PR, branch="spec/add-marker/1")
    forge.on_pr[PR] = {"held", "failed"}
    dispatch = events.build_dispatch(store, restack=lambda **_: None, log=lambda m: None)

    dispatch("rework", PR, repo="app", reason="new comment")

    assert store.get("add-marker/1").state == PLANNED
    assert state_labels_on(forge) == {"planned"}, "set from the unit's state, not read from it"


def test_the_label_follows_a_unit_through_the_changes_the_pipeline_makes(tmp_path: Path) -> None:
    """One state label at each step, and the previous one gone: a run that
    starts, opens its pull request, is sent back, rebuilds, and is held."""
    forge = StandInForge()
    store = wired(tmp_path, forge, [])
    store.upsert([unit("add-marker/1")])
    uid = "add-marker/1"
    dispatch = events.build_dispatch(store, restack=lambda **_: None, log=lambda m: None)

    store.set_state(uid, "running", branch="spec/add-marker/1")
    assert state_labels_on(forge) == set(), "no pull request yet, nothing to label"

    store.set_state(uid, IN_REVIEW, pr=PR, resume_from="")
    assert state_labels_on(forge) == {"in-review"}

    dispatch("rework", PR, repo="app", reason="review: changes requested")
    assert state_labels_on(forge) == {"planned"}

    store.set_state(uid, "running", branch="spec/add-marker/1")
    assert state_labels_on(forge) == {"running"}

    store.set_state(uid, "held", note="needs a human: stuck")
    assert state_labels_on(forge) == {"held"}

    store.set_state(uid, "failed")
    assert state_labels_on(forge) == {"failed"}

    store.set_state(uid, "merged")
    assert state_labels_on(forge) == {"failed"}, "merged adds none, and the host shows it"


def test_the_change_label_goes_on_when_the_pull_request_opens_and_stays(tmp_path: Path) -> None:
    forge = StandInForge()
    forge.on_pr[PR] = {"bug"}
    store = wired(tmp_path, forge, [])
    store.upsert([unit("add-marker/1")])

    store.set_state("add-marker/1", "running", branch="spec/add-marker/1")
    store.set_state("add-marker/1", IN_REVIEW, pr=PR)
    store.set_state("add-marker/1", "running")
    store.set_state("add-marker/1", IN_REVIEW)

    assert {"bug", change_label("add-marker").name, "in-review"} == on_pr(forge)
    tagged = [label for label in forge.label_creations if label == change_label("add-marker")]
    assert len(tagged) == 1


def test_a_state_change_reaches_the_forge_after_the_store_is_written(tmp_path: Path) -> None:
    seen: list[str] = []
    path = tmp_path / "units.json"
    store = UnitStore(
        path, on_state=lambda unit, units, opened: seen.append(UnitStore(path).get(unit.id).state)
    )
    store.upsert([unit("add-marker/1")])

    store.set_state("add-marker/1", IN_REVIEW, pr=PR)

    assert seen == [IN_REVIEW]
