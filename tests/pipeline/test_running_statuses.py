"""A running unit says whether it is building, reworking or rebasing.

The status is derived from the unit's record, never stored: the store holds
`running` for all three, and the status command, the graph and a pull
request's state label show the derived name and colour.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.labels import StateLabels
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING, UnitState
from agent_build_kit.pipeline.vocabulary import (
    STATES,
    effective_state,
    state_label,
    state_label_names,
)
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.forges.stand_in import StandInForge, lookup

NONE = FeedbackSource.NONE
PR = 7
UID = "add-marker/1"


def running(
    uid: str = UID, *, cause: str = "", source: FeedbackSource = FeedbackSource.NONE
) -> StoredUnit:
    """A unit running again after the entry that sent it back, as the store records it."""
    sent_back: dict[str, str] = {"state": "planned", "at": "t"}
    if cause:
        sent_back["cause"] = cause
    return stored_unit(
        uid,
        state="running",
        pr=PR,
        feedback="words" if source is not FeedbackSource.NONE else "",
        feedback_source=source,
        history=(sent_back, {"state": "running", "at": "t"}),
    )


def run_through_the_store(
    store: UnitStore,
    uid: str,
    *,
    cause: Cause | None = None,
    source: FeedbackSource = FeedbackSource.NONE,
) -> None:
    """Send a unit back and run it again, as the pipeline does."""
    store.upsert([stored_unit(uid)])
    if source is not FeedbackSource.NONE:
        store.set_feedback(uid, "words", source=source)
    if cause is not None:
        store.set_state(uid, PLANNED, cause=cause)
    store.set_state(uid, RUNNING)


@pytest.mark.parametrize(
    "cause", [Cause.BASE_CHANGED, Cause.RESTACK_CONFLICT, Cause.RESTACK_DEFERRED]
)
def test_a_unit_running_after_the_base_changed_or_a_restack_stopped_reads_rebasing(
    cause: Cause,
) -> None:
    unit = running(cause=cause.value)

    assert effective_state(unit, [unit]) == "rebasing"


def test_a_unit_running_to_resolve_a_conflict_reads_rebasing() -> None:
    unit = running(cause=Cause.REWORK.value, source=FeedbackSource.CONFLICT)

    assert effective_state(unit, [unit]) == "rebasing"


@pytest.mark.parametrize("source", [FeedbackSource.REVIEW, FeedbackSource.CI])
def test_a_unit_running_to_answer_review_or_check_feedback_reads_reworking(
    source: FeedbackSource,
) -> None:
    unit = running(cause=Cause.REWORK.value, source=source)

    assert effective_state(unit, [unit]) == "reworking"


def test_a_first_build_reads_running() -> None:
    unit = stored_unit(UID, state="running", history=({"state": "running", "at": "t"},))

    assert effective_state(unit, [unit]) == "running"


def test_a_unit_running_with_no_history_reads_running() -> None:
    unit = stored_unit(UID, state="running")

    assert effective_state(unit, [unit]) == "running"


def test_the_stored_state_is_running_for_all_three(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    run_through_the_store(store, "a/1", cause=Cause.BASE_CHANGED)
    run_through_the_store(store, "b/1", cause=Cause.REWORK, source=FeedbackSource.CI)
    run_through_the_store(store, "c/1")

    stored = store.all()
    units = {unit.id: effective_state(unit, stored) for unit in stored}
    assert units == {"a/1": "rebasing", "b/1": "reworking", "c/1": "running"}
    assert {unit.id: unit.state for unit in stored} == {
        "a/1": RUNNING,
        "b/1": RUNNING,
        "c/1": RUNNING,
    }


def test_each_derived_status_has_its_own_name_and_colour() -> None:
    assert STATES["rebasing"].name == "rebasing"
    assert STATES["reworking"].name == "reworking"
    strokes = {STATES[key].stroke for key in ("running", "rebasing", "reworking")}
    assert len(strokes) == 3, "the three must be told apart by colour"


def test_each_derived_status_has_a_state_label_named_as_the_graph_writes_it() -> None:
    for key in ("rebasing", "reworking"):
        label = state_label(key)

        assert label is not None, key
        assert label.name == STATES[key].name
        assert label.color == STATES[key].stroke.removeprefix("#")
        assert label.description


def test_the_graph_shows_the_derived_name_and_class() -> None:
    rebasing = running("a/1", cause=Cause.BASE_CHANGED.value)
    reworking = running("b/1", cause=Cause.REWORK.value, source=FeedbackSource.REVIEW)
    building = stored_unit("c/1", state="running")

    diagram = render_mermaid([rebasing, reworking, building])

    assert "· rebasing" in diagram
    assert "· reworking" in diagram
    assert "class a_1 rebasing" in diagram
    assert "class b_1 reworking" in diagram
    assert "class c_1 running" in diagram


def test_the_state_label_on_a_pull_request_follows_the_derived_status(tmp_path: Path) -> None:
    forge = StandInForge()
    labels = StateLabels(lookup(forge), log=lambda line: None)
    store = UnitStore(
        tmp_path / "units.json",
        on_state=lambda unit, units, opened: labels.follow(unit, units, opened=opened),
    )
    store.upsert([stored_unit(UID)])
    store.set_state(UID, IN_REVIEW, pr=PR, branch="spec/add-marker/1")
    store.set_feedback(UID, "fix the name", source=FeedbackSource.REVIEW)
    store.set_state(UID, PLANNED, cause=Cause.REWORK)

    store.set_state(UID, RUNNING)

    assert forge.on_pr[PR] & state_label_names() == {"reworking"}


def test_status_counts_units_by_the_derived_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    run_through_the_store(store, "a/1", cause=Cause.BASE_CHANGED)
    run_through_the_store(store, "b/1", cause=Cause.REWORK, source=FeedbackSource.CI)
    run_through_the_store(store, "c/1")
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    units_line = next(line for line in capsys.readouterr().out.splitlines() if "] units: " in line)
    assert "1 rebasing" in units_line
    assert "1 reworking" in units_line
    assert "1 running" in units_line


def as_the_graph_records(
    store: UnitStore, uid: str, *, first: UnitState, cause: Cause, source: FeedbackSource = NONE
) -> None:
    """Move a unit as the graph's events do: the event's own `running` entry carries
    the cause, and `prepare` then adds a `running` entry with none."""
    store.upsert([stored_unit(uid)])
    store.set_state(uid, first)
    if source is not NONE:
        store.set_feedback(uid, "words", source=source)
    store.set_state(uid, RUNNING, cause=cause)
    store.set_state(uid, RUNNING)


def status_of(store: UnitStore, uid: str) -> str:
    units = store.all()
    return effective_state(next(unit for unit in units if unit.id == uid), units)


def test_a_unit_in_review_whose_base_moved_in_the_graph_reads_rebasing(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")

    as_the_graph_records(store, UID, first=IN_REVIEW, cause=Cause.BASE_CHANGED)

    assert status_of(store, UID) == "rebasing"


def test_a_review_comment_during_a_rebase_reads_reworking(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(UID)])
    store.set_state(UID, PLANNED, cause=Cause.BASE_CHANGED)
    store.set_state(UID, RUNNING)
    store.set_feedback(UID, "fix the name", source=FeedbackSource.REVIEW)

    store.set_state(UID, RUNNING, cause=Cause.REWORK)

    assert status_of(store, UID) == "reworking"


def test_a_conflict_during_a_graph_rework_reads_rebasing(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")

    as_the_graph_records(
        store, UID, first=IN_REVIEW, cause=Cause.REWORK, source=FeedbackSource.CONFLICT
    )

    assert status_of(store, UID) == "rebasing"


def test_a_cause_from_before_the_unit_last_started_running_is_not_read(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(UID)])
    store.set_state(UID, PLANNED, cause=Cause.BASE_CHANGED)
    store.set_state(UID, RUNNING)
    store.set_state(UID, IN_REVIEW)
    store.set_state(UID, PLANNED)

    store.set_state(UID, RUNNING)

    assert status_of(store, UID) == "running"
