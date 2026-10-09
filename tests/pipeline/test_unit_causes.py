"""A unit's state changes record why, as a defined cause, and nothing reads a note.

The note stays as prose for people. These pin the field: what writes it, how a
store from before it loads, and that no module is left deciding from wording.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import agent_build_kit
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED, RUNNING
from agent_build_kit.pipeline.vocabulary import effective_state
from tests.factories import stored_unit, unit

UNIT = "add-marker/1"


@pytest.fixture
def store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT)])
    return store


def last_cause(store: UnitStore, unit_id: str = UNIT) -> str | None:
    return store.history(unit_id)[-1].get("cause")


def test_the_causes_are_the_fixed_set_the_design_names() -> None:
    assert {cause.value for cause in Cause} == {
        "rework",
        "base_changed",
        "upstream_went_back",
        "usage",
        "depth",
        "toolchain",
        "review_escalated_class",
        "review_escalated_disagreement",
        "needs_human",
        "reviewer_hold",
        "requeued",
        "gated",
        "released",
        "restack_conflict",
        "restack_deferred",
        "dirty_worktree",
        "merged",
        "closed",
        "failed",
        "host_unavailable",
    }


@pytest.mark.parametrize("cause", list(Cause))
def test_a_state_change_records_its_cause_on_the_history_entry(
    store: UnitStore, cause: Cause
) -> None:
    store.set_state(UNIT, PLANNED, note="any words at all", cause=cause)

    assert last_cause(store) == cause
    assert store.history(UNIT)[-1]["note"] == "any words at all"


def test_the_cause_survives_a_reload_as_an_enum_value(store: UnitStore) -> None:
    store.set_state(UNIT, PLANNED, cause=Cause.BASE_CHANGED)

    raw = json.loads(store.path.read_text())

    assert raw["units"][0]["history"][-1]["cause"] == "base_changed"


def test_a_cause_this_release_does_not_know_reads_as_none(store: UnitStore) -> None:
    store.set_state(UNIT, PLANNED, cause=Cause.BASE_CHANGED)
    store.path.write_text(store.path.read_text().replace("base_changed", "from_a_later_release"))

    assert UnitStore(store.path).get(UNIT).cause is None


def test_a_state_change_without_a_cause_records_none_even_after_one_with(
    store: UnitStore,
) -> None:
    store.set_state(UNIT, PLANNED, note="rework requested: x", cause=Cause.REWORK)
    store.set_state(UNIT, RUNNING)

    assert last_cause(store) is None


def test_a_depth_hold_stores_the_base_it_is_still_on_as_a_field(store: UnitStore) -> None:
    store.set_state(
        UNIT, HELD, note="prose", held_by=HeldBy.DEPTH, cause=Cause.DEPTH, held_base="spec/c/1"
    )

    stored = store.get(UNIT)
    assert (stored.held_by, stored.held_base) == (HeldBy.DEPTH, "spec/c/1")


def test_the_base_a_depth_hold_was_on_is_forgotten_once_the_unit_is_not_held(
    store: UnitStore,
) -> None:
    store.set_state(UNIT, HELD, held_by=HeldBy.DEPTH, cause=Cause.DEPTH, held_base="spec/c/1")
    store.set_state(UNIT, IN_REVIEW, pr=1)

    assert store.get(UNIT).held_base == ""


# --- a store from before causes --------------------------------------------------------

OLD_NOTES = [
    "held before implement: its base moved from spec/a/1 to main while it built",
    "rework requested: merge conflict with its base",
    "held by a reviewer",
    "too deep (still on spec/c/1)",
]


def old_store(tmp_path: Path, state: str, note: str) -> UnitStore:
    """A store as an earlier version wrote it: a history entry with only a note,
    and neither `held_by` nor `held_base` on the unit."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(UNIT)])
    raw = json.loads(store.path.read_text())
    item = raw["units"][0]
    item.pop("held_by", None)
    item.pop("held_base", None)
    item["state"] = state
    item["history"] = [{"state": state, "at": "2020-01-01T00:00:00+00:00", "note": note}]
    store.path.write_text(json.dumps(raw))
    return store


@pytest.mark.parametrize("note", OLD_NOTES)
@pytest.mark.parametrize("state", [PLANNED, HELD])
def test_an_old_entry_loads_with_no_cause_no_holder_and_no_base(
    tmp_path: Path, state: str, note: str
) -> None:
    store = old_store(tmp_path, state, note)

    stored = store.get(UNIT)
    assert last_cause(store) is None
    assert stored.held_by == HeldBy.NONE
    assert stored.held_base == ""
    assert not stored.held_by_the_label, "a note is not read to say a reviewer held it"


def test_an_old_reviewer_hold_note_does_not_make_the_unit_the_labels(tmp_path: Path) -> None:
    store = old_store(tmp_path, HELD, "held by a reviewer")

    assert not store.get(UNIT).held_by_the_label


# --- the diagram follows the cause, not the wording ------------------------------------


def waiting(cause: Cause | None, note: str):
    parent = stored_unit("add-marker/0", state="failed")
    entry: dict = {"state": "planned", "at": "t", "note": note}
    if cause is not None:
        entry["cause"] = cause.value
    child = stored_unit(UNIT, depends_on=("add-marker/0",), state="planned", history=(entry,))
    return child, [parent, child]


@pytest.mark.parametrize("cause", [Cause.BASE_CHANGED, Cause.UPSTREAM_WENT_BACK])
def test_a_waiting_unit_stopped_for_its_upstream_or_base_reads_as_paused_whatever_its_note(
    cause: Cause,
) -> None:
    child, graph = waiting(cause, "something else entirely")

    assert effective_state(child, graph) == "paused_rework"


@pytest.mark.parametrize("note", ["held before implement: x", "held after implement: x", ""])
def test_a_waiting_unit_with_no_cause_reads_as_blocked_whatever_its_note(note: str) -> None:
    child, graph = waiting(None, note)

    assert effective_state(child, graph) == "blocked"


@pytest.mark.parametrize("cause", [Cause.USAGE, Cause.REQUEUED, Cause.RESTACK_CONFLICT])
def test_a_waiting_unit_stopped_for_another_cause_reads_as_blocked_though_its_note_says_held(
    cause: Cause,
) -> None:
    child, graph = waiting(cause, "held before implement: its base moved")

    assert effective_state(child, graph) == "blocked"


# --- no module reads a note ------------------------------------------------------------

DELETED_NAMES = ("held_for_base", "_DEPTH_HOLD", "_depth_hold_base")
NOTE_PREFIX_CHECKS = re.compile(
    r"""startswith\(\s*\(?\s*["'](held (before|after)|rework requested)|==\s*HELD_BY_A_REVIEWER"""
)


def sources() -> list[tuple[Path, str]]:
    root = Path(agent_build_kit.__file__).parent
    return [(path, path.read_text()) for path in sorted(root.rglob("*.py"))]


@pytest.mark.parametrize("name", DELETED_NAMES)
def test_no_module_still_has_a_deleted_note_matcher(name: str) -> None:
    users = [path.name for path, text in sources() if re.search(rf"\b{name}\b", text)]

    assert users == []


def test_no_module_tests_a_note_by_its_prefix() -> None:
    users = [path.name for path, text in sources() if NOTE_PREFIX_CHECKS.search(text)]

    assert users == []
