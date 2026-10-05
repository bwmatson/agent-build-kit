"""Where units and their state actually live.

Units are tracked in the planning repo, not as GitHub issues
(docs/architecture.md). One file, versioned beside the specs,
trivially resettable, and it leaves no debris in app or platform when a
change is re-planned or abandoned.

The trade is that nothing closes a unit automatically on merge, so the store
has to be written honestly by the runner — which makes "does a reload see what
the last process wrote" the property that matters most here.
"""

import json

import pytest

from agent_build_kit.pipeline.unit_store import UNPLANNED, UnitStore, corrupt_store_message
from agent_build_kit.pipeline.units import CLOSED, IN_REVIEW, MERGED, PLANNED, Unit
from tests.factories import unit as app_unit


def unit(uid: str = "add-marker/1", **overrides) -> Unit:
    """platform, so a round trip can't pass by echoing the default repo."""
    return app_unit(uid, **{"repo": "platform", **overrides})


def test_units_survive_a_restart(tmp_path) -> None:
    """Each scheduler tick is a new process; in-memory state would be lost
    between every round."""
    path = tmp_path / "units.json"
    UnitStore(path).upsert([unit()])

    reloaded = UnitStore(path).all()

    assert [u.id for u in reloaded] == ["add-marker/1"]
    assert reloaded[0].repo == "platform"


def test_replanning_updates_a_unit_rather_than_duplicating_it(tmp_path) -> None:
    """The graph is re-derived every round, so the same unit arrives again and
    again. Appending would grow the store without bound."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(title="first wording")])

    store.upsert([unit(title="second wording")])

    assert len(store.all()) == 1
    assert store.all()[0].title == "second wording"


def test_replanning_does_not_forget_progress(tmp_path) -> None:
    """A re-planned unit keeps its state and branch: the planner proposes
    shape, not history, and losing state would rebuild merged work."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state("add-marker/1", MERGED, pr=7)

    store.upsert([unit(title="re-planned")])

    kept = store.get("add-marker/1")
    assert kept.state == MERGED
    assert kept.pr == 7


def test_state_changes_are_recorded_with_when(tmp_path) -> None:
    """Without a timestamp the run log can't answer "when did this stall"."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])

    store.set_state("add-marker/1", IN_REVIEW, pr=4)

    history = store.history("add-marker/1")
    assert [entry["state"] for entry in history] == ["planned", "in_review"]
    assert all("at" in entry for entry in history)


def test_a_unit_that_vanishes_from_the_plan_is_kept_but_marked(tmp_path) -> None:
    """Deleting it would lose the record of work that may already be open; the
    runner needs to see that the plan changed underneath it."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("add-marker/1"), unit("add-marker/2")])

    store.upsert([unit("add-marker/1")], change="add-marker")

    assert {u.id for u in store.all()} == {"add-marker/1", "add-marker/2"}
    assert store.get("add-marker/2").state == "unplanned"


def test_a_corrupt_store_refuses_rather_than_starting_over(tmp_path) -> None:
    """Unlike a cache, this is the source of truth. Treating an unreadable
    file as "no units" would re-plan and rebuild work already merged."""
    path = tmp_path / "units.json"
    path.write_text("{not json")

    with pytest.raises(ValueError, match=corrupt_store_message(path)):
        UnitStore(path).all()


def test_an_absent_store_is_simply_empty(tmp_path) -> None:
    """First run: nothing planned yet is not an error."""
    assert UnitStore(tmp_path / "units.json").all() == []


def test_a_stored_unit_without_merge_before_loads_unchanged(tmp_path) -> None:
    """Records written before the field existed are still on disk in every
    installation; the field is optional so they keep loading."""
    path = tmp_path / "units.json"
    UnitStore(path).upsert([unit("add-marker/2", depends_on=("add-marker/1",), groups=(2,))])
    raw = json.loads(path.read_text())
    for record in raw["units"].values() if isinstance(raw["units"], dict) else raw["units"]:
        record.pop("merge_before", None)
    path.write_text(json.dumps(raw))
    assert "merge_before" not in path.read_text()

    store = UnitStore(path)

    for loaded in (store.get("add-marker/2"), store.all()[0]):
        assert loaded.merge_before == ()
        assert loaded.depends_on == ("add-marker/1",)
        assert loaded.groups == (2,)
        assert loaded.repo == "platform"


def test_the_file_is_readable_by_a_human(tmp_path) -> None:
    """It is committed to the planning repo, so it shows up in diffs and
    reviews; dense JSON would make those useless."""
    path = tmp_path / "units.json"
    UnitStore(path).upsert([unit()])

    text = path.read_text()

    assert text.count("\n") > 5
    assert '"id": "add-marker/1"' in text


def test_the_last_pushed_sha_survives_the_process_that_pushed_it(tmp_path) -> None:
    """The lease on the next push is `--force-with-lease=<branch>:<sha>`, and
    that sha is the one *this* runner last published. A tick is a separate
    process from the one before it, so remembering it in memory is no use."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])

    store.record_push("add-marker/1", "abc1234")

    assert UnitStore(tmp_path / "units.json").get("add-marker/1").pushed == "abc1234"


def test_re_planning_does_not_forget_what_was_pushed(tmp_path) -> None:
    """Losing it would silently downgrade the next push to a first push, which
    is the one case that needs no force and so would be rejected outright."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.record_push("add-marker/1", "abc1234")

    store.upsert([unit(title="Renamed after a re-plan")])

    assert store.get("add-marker/1").pushed == "abc1234"


def test_a_stored_unit_can_be_fed_back_into_the_plan(tmp_path) -> None:
    """`all()` hands back StoredUnits, and a StoredUnit is a Unit, so nothing
    stops a caller re-planning with one. Its recorded fields have to be taken
    from the store rather than from the unit passed in, or they collide."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state("add-marker/1", IN_REVIEW, pr=7)

    store.upsert(store.all())

    assert store.get("add-marker/1").pr == 7


def test_replanning_does_not_unplan_a_unit_that_already_merged(tmp_path) -> None:
    """After a unit merges, its change is re-planned and the new plan
    correctly covers only the remaining unit — so upsert would mark the
    merged one `unplanned`. Its work is in main; it cannot be unplanned. And
    archiving requires every unit merged, so the change could never archive."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1", change="c"), unit("c/2", change="c")], change="c")
    store.set_state("c/1", MERGED, pr=1)

    store.upsert([unit("c/2", change="c")], change="c")

    assert store.get("c/1").state == MERGED


def test_replanning_still_unplans_a_unit_that_never_started(tmp_path) -> None:
    """The mechanism has to keep working: a planned unit the latest plan drops
    is genuinely no longer wanted."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1", change="c"), unit("c/2", change="c")], change="c")

    store.upsert([unit("c/2", change="c")], change="c")

    assert store.get("c/1").state == UNPLANNED


def test_replanning_does_not_unplan_a_unit_that_was_closed(tmp_path) -> None:
    """Closed is a decision someone made about that unit, and its branch still
    holds the work. Overwriting it with `unplanned` loses which it was."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1", change="c"), unit("c/2", change="c")], change="c")
    store.set_state("c/1", CLOSED, pr=1)

    store.upsert([unit("c/2", change="c")], change="c")

    assert store.get("c/1").state == CLOSED


def test_a_unit_the_plan_wants_again_is_planned_again(tmp_path) -> None:
    """`upsert` carried the existing state over for every unit in the plan, so
    a unit once marked `unplanned` stayed that way even when a later plan asked
    for it. `ready_units` only picks `planned`, so it could never build — and
    anything depending on it was blocked for good, along with every unit
    behind it."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1", change="c"), unit("c/2", change="c")], change="c")
    store.upsert([unit("c/1", change="c")], change="c")
    assert store.get("c/2").state == UNPLANNED

    store.upsert([unit("c/1", change="c"), unit("c/2", change="c")], change="c")

    assert store.get("c/2").state == PLANNED


def test_progress_on_a_unit_is_not_reset_by_a_replan(tmp_path) -> None:
    """Only `unplanned` is reversible this way. A unit that is running, open or
    merged keeps its state — re-planning is not a reason to rebuild it."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1", change="c")], change="c")
    store.set_state("c/1", IN_REVIEW, pr=7)

    store.upsert([unit("c/1", change="c")], change="c")

    assert store.get("c/1").state == IN_REVIEW


def test_unplanning_and_replanning_are_both_recorded(tmp_path) -> None:
    """The demotion left no history entry at all, so there was no trace of when
    a unit was dropped or why it could not run. Every other state change goes
    through `set_state` and is recorded; this one bypassed it."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1", change="c"), unit("c/2", change="c")], change="c")

    store.upsert([unit("c/1", change="c")], change="c")
    store.upsert([unit("c/1", change="c"), unit("c/2", change="c")], change="c")

    states = [e["state"] for e in store.get("c/2").history]
    assert states == [PLANNED, UNPLANNED, PLANNED]


def test_a_unit_in_flight_is_not_unplanned_by_a_replan(tmp_path) -> None:
    """The planner is told about in-flight units as context so it stops
    proposing them — so every re-plan omits them, and demoting on absence
    demoted the unit that was actually building: a unit `unplanned` while
    its PR is open blocks every unit behind it.

    Only a unit that never started can be dropped; that is the whole set the
    mechanism was ever for."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit("c/1", change="c"), unit("c/2", change="c")], change="c")
    store.set_state("c/1", "running")
    store.set_state("c/2", IN_REVIEW, pr=4)

    store.upsert([], change="c")

    assert store.get("c/1").state == "running"
    assert store.get("c/2").state == IN_REVIEW


def test_every_write_is_seen_by_the_listener(tmp_path) -> None:
    """How the diagram stays current: one hook on the store, rather than every
    place that changes a state remembering to redraw it."""
    seen: list[list[str]] = []
    store = UnitStore(
        tmp_path / "units.json", on_write=lambda units: seen.append([u.state for u in units])
    )
    store.upsert([unit()])
    store.set_state("add-marker/1", "running")

    assert seen == [["planned"], ["running"]]


def test_changes_made_at_the_same_time_are_all_kept(tmp_path) -> None:
    """Units build in parallel, and each change is a read-modify-write of one
    file. Unlocked, two writers read the same version and the second write
    drops the first's change."""
    from concurrent.futures import ThreadPoolExecutor

    store = UnitStore(tmp_path / "units.json")
    ids = [f"c/{n}" for n in range(8)]
    store.upsert([unit(uid) for uid in ids])

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda uid: store.record_push(uid, f"sha-{uid}"), ids))

    assert [store.get(uid).pushed for uid in ids] == [f"sha-{uid}" for uid in ids]


def test_re_planning_keeps_feedback(tmp_path) -> None:
    """Feedback is work in progress, not shape. A re-plan dropped the feedback
    waiting to be addressed, so the next run built as if nobody had asked."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_feedback("add-marker/1", "rename it")

    store.upsert([unit(title="retitled by the plan")])

    assert store.get("add-marker/1").feedback == "rename it"
