"""A unit's state, on its pull request.

Labelling is cosmetic: one state label at a time, the graph's words, and no
failure of it is ever a unit's problem. The forge is a stand-in that records
which labels each pull request carries.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.labels import ClearOutcome, StateLabels
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, Member, UnitState
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


class NoLabelsForge(StandInForge):
    """A host that has no labels at all: every label call is unimplemented."""

    def add_label(self, *args, **kwargs) -> None:
        raise NotImplementedError

    def set_exclusive_label(self, *args, **kwargs) -> None:
        raise NotImplementedError

    def remove_label(self, *args, **kwargs) -> None:
        raise NotImplementedError


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


def test_a_host_that_keeps_no_labels_is_said_once_and_changes_nothing(tmp_path: Path) -> None:
    logged: list[str] = []
    store = wired(tmp_path, NoLabelsForge(), logged)
    store.upsert([unit("add-marker/1")])

    store.set_state("add-marker/1", UnitState.RUNNING, branch="spec/add-marker/1")
    store.set_state("add-marker/1", IN_REVIEW, pr=PR)
    store.set_state("add-marker/1", UnitState.RUNNING)
    store.set_state("add-marker/1", UnitState.HELD)

    assert store.get("add-marker/1").state == "held"
    assert len(logged) == 1, logged
    assert "no labels" in logged[0]
    assert not any("failed" in line for line in logged)


def test_a_host_that_keeps_no_labels_leaves_an_instruction_label_unconsumed(
    logged: list[str],
) -> None:
    labels = StateLabels(lookup(NoLabelsForge()), log=logged.append)

    assert labels.consume("app", PR, "agent-rework") is False


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

    store.set_state(uid, UnitState.RUNNING, branch="spec/add-marker/1")
    assert state_labels_on(forge) == set(), "no pull request yet, nothing to label"

    store.set_state(uid, IN_REVIEW, pr=PR)
    assert state_labels_on(forge) == {"in-review"}

    dispatch("rework", PR, repo="app", reason="review: changes requested")
    assert state_labels_on(forge) == {"planned"}

    store.set_state(uid, UnitState.RUNNING, branch="spec/add-marker/1")
    assert state_labels_on(forge) == {"running"}

    store.set_state(uid, UnitState.HELD, note="needs a human: stuck")
    assert state_labels_on(forge) == {"held"}

    store.set_state(uid, UnitState.FAILED)
    assert state_labels_on(forge) == {"failed"}

    store.set_state(uid, UnitState.MERGED)
    assert state_labels_on(forge) == set(), "merged adds none and takes the last one off"


def test_the_change_label_goes_on_when_the_pull_request_opens_and_stays(tmp_path: Path) -> None:
    forge = StandInForge()
    forge.on_pr[PR] = {"bug"}
    store = wired(tmp_path, forge, [])
    store.upsert([unit("add-marker/1")])

    store.set_state("add-marker/1", UnitState.RUNNING, branch="spec/add-marker/1")
    store.set_state("add-marker/1", IN_REVIEW, pr=PR)
    store.set_state("add-marker/1", UnitState.RUNNING)
    store.set_state("add-marker/1", IN_REVIEW)

    assert {"bug", change_label("add-marker").name, "in-review"} == on_pr(forge)
    tagged = [label for _, label in forge.added if label == change_label("add-marker")]
    assert len(tagged) == 1, "put on when the pull request opened, not at each state change"


def test_a_unit_that_joined_another_changes_groups_carries_a_label_for_each(
    tmp_path: Path,
) -> None:
    forge = StandInForge()
    store = wired(tmp_path, forge, [])
    store.upsert([unit("add-marker/1", joined=(Member(change="feature", groups=(1,)),))])

    store.set_state("add-marker/1", IN_REVIEW, pr=PR, branch="spec/add-marker/1")
    store.set_state("add-marker/1", UnitState.RUNNING)

    own, other = change_label("add-marker"), change_label("feature")
    assert {own.name, other.name} <= on_pr(forge)
    for label in (own, other):
        assert [added for _, added in forge.added].count(label) == 1, label.name


def test_a_state_change_reaches_the_forge_after_the_store_is_written(tmp_path: Path) -> None:
    seen: list[str] = []
    path = tmp_path / "units.json"
    store = UnitStore(
        path, on_state=lambda unit, units, opened: seen.append(UnitStore(path).get(unit.id).state)
    )
    store.upsert([unit("add-marker/1")])

    store.set_state("add-marker/1", IN_REVIEW, pr=PR)

    assert seen == [IN_REVIEW]


# --- a unit that finishes has its state label taken off -------------------------------

FINISHED = (UnitState.MERGED, UnitState.CLOSED, UnitState.SATISFIED, UnitState.UNPLANNED)


def follow(labels: StateLabels, state: UnitState, *, pr: int | None = PR) -> None:
    one = unit("add-marker/1", state=state, pr=pr)
    labels.follow(one, [one], opened=False)


def test_a_unit_that_merges_loses_its_in_review_label(
    forge: StandInForge, labels: StateLabels
) -> None:
    forge.on_pr[PR] = {"in-review"}

    follow(labels, UnitState.MERGED)

    assert state_labels_on(forge) == set()


@pytest.mark.parametrize("carried", ["checking", "running", "held", "planned", "in-review"])
def test_a_unit_that_is_closed_loses_whichever_state_label_it_carried(
    carried: str, forge: StandInForge, labels: StateLabels
) -> None:
    forge.on_pr[PR] = {carried}

    follow(labels, UnitState.CLOSED)

    assert state_labels_on(forge) == set()


@pytest.mark.parametrize("state", [UnitState.SATISFIED, UnitState.UNPLANNED])
def test_a_satisfied_or_unplanned_unit_with_a_pull_request_is_cleared(
    state: UnitState, forge: StandInForge, labels: StateLabels
) -> None:
    forge.on_pr[PR] = {"in-review"}

    follow(labels, state)

    assert state_labels_on(forge) == set()


@pytest.mark.parametrize("state", FINISHED)
def test_a_finished_unit_with_no_pull_request_makes_no_forge_call(
    state: UnitState, forge: StandInForge, labels: StateLabels
) -> None:
    follow(labels, state, pr=None)

    assert forge.label_reads == []
    assert forge.label_removals == []


def test_the_change_label_and_a_label_a_person_added_stay(
    forge: StandInForge, labels: StateLabels
) -> None:
    forge.on_pr[PR] = {"in-review", "bug", change_label("add-marker").name}

    follow(labels, UnitState.MERGED)

    assert on_pr(forge) == {"bug", change_label("add-marker").name}


def test_the_pull_request_is_read_once_and_only_the_state_labels_it_carries_are_removed(
    forge: StandInForge, labels: StateLabels
) -> None:
    forge.on_pr[PR] = {"in-review", "checking", "bug"}

    follow(labels, UnitState.CLOSED)

    assert forge.label_reads == [PR]
    assert sorted(forge.label_removals) == [(PR, "checking"), (PR, "in-review")]


def test_clearing_reports_what_it_did(forge: StandInForge, labels: StateLabels) -> None:
    forge.on_pr[PR] = {"in-review", "bug"}

    assert labels.clear_state("app", PR) == ClearOutcome.CLEARED
    assert labels.clear_state("app", PR) == ClearOutcome.NOTHING_TO_CLEAR


def test_a_pull_request_with_no_state_label_is_nothing_to_clear_and_no_fault(
    forge: StandInForge, labels: StateLabels, logged: list[str]
) -> None:
    forge.on_pr[PR] = {"bug"}

    assert labels.clear_state("app", PR) == ClearOutcome.NOTHING_TO_CLEAR

    assert forge.label_removals == []
    assert logged == []


class NoReadForge(StandInForge):
    """A host whose labels cannot be read: `labels_on` is unimplemented."""

    def labels_on(self, *args, **kwargs) -> list[str]:
        raise NotImplementedError


def test_a_host_that_cannot_read_labels_is_not_a_fault_and_is_said_once(
    logged: list[str],
) -> None:
    labels = StateLabels(lookup(NoReadForge()), log=logged.append)

    assert labels.clear_state("app", PR) == ClearOutcome.NOTHING_TO_CLEAR
    assert labels.clear_state("app", 8) == ClearOutcome.NOTHING_TO_CLEAR

    assert len(logged) == 1, logged
    assert "no labels" in logged[0]
    assert "failed" not in logged[0]


@pytest.mark.parametrize("failing", ["read", "remove"])
def test_a_failed_read_or_removal_is_logged_once_and_the_outcome_is_failed(
    failing: str, logged: list[str]
) -> None:
    forge = StandInForge(label_errors=(failing,))
    forge.on_pr[PR] = {"in-review"}
    labels = StateLabels(lookup(forge), log=logged.append)

    assert labels.clear_state("app", PR) == ClearOutcome.FAILED

    assert len(logged) == 1, logged
    assert "failed" in logged[0]


def test_a_failed_clear_leaves_the_unit_finished(tmp_path: Path) -> None:
    logged: list[str] = []
    forge = StandInForge(label_errors=("read", "remove"))
    store = wired(tmp_path, forge, logged)
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", IN_REVIEW, pr=PR, branch="spec/add-marker/1")

    store.set_state("add-marker/1", UnitState.MERGED)

    assert store.get("add-marker/1").state == UnitState.MERGED
    assert len(logged) == 1, logged


def test_a_merge_delivered_twice_removes_nothing_the_second_time(tmp_path: Path) -> None:
    logged: list[str] = []
    forge = StandInForge()
    store = wired(tmp_path, forge, logged)
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", IN_REVIEW, pr=PR, branch="spec/add-marker/1")

    store.set_state("add-marker/1", UnitState.MERGED)
    store.set_state("add-marker/1", UnitState.MERGED)

    assert forge.label_removals == [(PR, "in-review")]
    assert logged == []


def test_a_labelled_state_still_sets_its_label_and_reads_nothing(
    forge: StandInForge, labels: StateLabels
) -> None:
    forge.on_pr[PR] = {"in-review", "bug"}

    labels.set_state("app", PR, "held")

    assert on_pr(forge) == {"held", "bug"}
    assert forge.label_reads == []
