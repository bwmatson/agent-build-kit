"""Where units and their state actually live.

Units are tracked in the planning repo, not as GitHub issues
(docs/architecture.md). One file, versioned beside the specs,
trivially resettable, and it leaves no debris in app or platform when a
change is re-planned or abandoned.

The trade is that nothing closes a unit automatically on merge, so the store
has to be written honestly by the runner — which makes "does a reload see what
the last process wrote" the property that matters most here.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.orchestration.stand_in import InMemoryUnitsStore
from agent_build_kit.orchestration.store import VersionConflict
from agent_build_kit.pipeline.unit_store import (
    REQUEUE_BY,
    RETRY_BY,
    UNPLANNED,
    AutoRework,
    Cause,
    RewriteSource,
    StoredRewriteRequest,
    UnitStore,
    corrupt_store_message,
)
from agent_build_kit.pipeline.units import (
    CLOSED,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    Unit,
    UnitState,
)
from tests.factories import stored_unit
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


def test_a_stored_unit_without_newer_optional_fields_loads_unchanged(tmp_path) -> None:
    """Records written before an optional field existed are still on disk in
    every installation; they keep loading."""
    path = tmp_path / "units.json"
    UnitStore(path).upsert([unit("add-marker/2", depends_on=("add-marker/1",), groups=(2,))])
    raw = json.loads(path.read_text())
    for record in raw["units"].values() if isinstance(raw["units"], dict) else raw["units"]:
        record.pop("merge_before", None)
    path.write_text(json.dumps(raw))
    assert "merge_before" not in path.read_text()

    store = UnitStore(path)

    for loaded in (store.get("add-marker/2"), store.all()[0]):
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
    store.set_state("c/1", UnitState.RUNNING)
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
    store.set_state("add-marker/1", UnitState.RUNNING)

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


def _history_text(store: UnitStore, uid: str = "add-marker/1") -> str:
    return " ".join(str(v) for entry in store.get(uid).history for v in entry.values()).lower()


@pytest.mark.parametrize("source", list(RewriteSource))
def test_a_rewrite_request_keeps_its_text_and_source_across_a_reload(tmp_path, source) -> None:
    path = tmp_path / "units.json"
    UnitStore(path).upsert([unit()])
    assert UnitStore(path).get("add-marker/1").rewrite_request is None
    asked = StoredRewriteRequest(text="move the support edits into the feat commit", source=source)

    UnitStore(path).set_rewrite_request("add-marker/1", asked)

    assert UnitStore(path).get("add-marker/1").rewrite_request == asked


@pytest.mark.parametrize("source", list(RewriteSource))
def test_the_history_records_that_a_rewrite_request_was_made_and_by_whom(tmp_path, source) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])

    store.set_rewrite_request("add-marker/1", StoredRewriteRequest(text="squash", source=source))

    said = _history_text(store)
    assert "rewrite" in said
    assert source.value in said


@pytest.mark.parametrize(
    ("asked_by", "requeued", "expected"),
    [
        ([RewriteSource.COMMIT_SHAPE], False, True),
        ([RewriteSource.COMMIT_SHAPE], True, False),
        ([RewriteSource.REVIEW], False, False),
        ([RewriteSource.PERSON], False, False),
        ([RewriteSource.REVIEW, RewriteSource.COMMIT_SHAPE], False, True),
    ],
    ids=["asked", "asked then requeued", "review only", "person only", "review then check"],
)
def test_a_commit_shape_ask_counts_only_since_the_latest_requeue_by_a_person(
    tmp_path, asked_by, requeued, expected
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    for source in asked_by:
        store.set_rewrite_request("add-marker/1", StoredRewriteRequest(text="x", source=source))
    if requeued:
        store.set_state("add-marker/1", PLANNED, by=REQUEUE_BY)

    assert store.rewrite_asked_by("add-marker/1", RewriteSource.COMMIT_SHAPE) is expected


def test_ending_a_step_clears_the_rewrite_request_and_the_history_says_it_was_used(
    tmp_path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    asked = StoredRewriteRequest(text="squash", source=RewriteSource.REVIEW)
    store.set_rewrite_request("add-marker/1", asked)

    store.clear_rewrite_request("add-marker/1")

    assert store.get("add-marker/1").rewrite_request is None
    assert "used" in str(store.get("add-marker/1").history[-1]).lower()


def test_ending_a_step_with_no_rewrite_request_records_nothing(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    before = store.get("add-marker/1")

    store.clear_rewrite_request("add-marker/1")

    assert store.get("add-marker/1") == before


def test_a_retry_adds_one_history_entry_by_the_pipeline_with_its_note(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    before = len(store.history("add-marker/1"))

    store.record_retry("add-marker/1", "time limit", "time limit: runs once more by itself")

    entries = store.history("add-marker/1")
    assert len(entries) == before + 1
    assert entries[-1]["by"] == RETRY_BY
    assert entries[-1]["note"].startswith("time limit")


def test_a_history_with_no_retry_entry_reads_as_not_spent(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])

    assert not store.retry_spent("add-marker/1", "time limit")


def test_a_retry_reads_as_spent_for_its_own_cause_only(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.record_retry("add-marker/1", "time limit", "time limit: runs once more by itself")

    assert store.retry_spent("add-marker/1", "time limit")
    assert not store.retry_spent("add-marker/1", "suspended")


@pytest.mark.parametrize(
    ("state", "by"), [(IN_REVIEW, ""), (PLANNED, REQUEUE_BY)], ids=["review", "person's requeue"]
)
def test_a_retry_before_review_or_a_requeue_by_a_person_reads_as_not_spent(
    tmp_path, state, by
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.record_retry("add-marker/1", "time limit", "time limit: runs once more by itself")

    store.set_state("add-marker/1", state, by=by)

    assert not store.retry_spent("add-marker/1", "time limit")


def test_a_retry_after_a_requeue_by_a_person_reads_as_spent(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state("add-marker/1", PLANNED, by=REQUEUE_BY)

    store.record_retry("add-marker/1", "time limit", "time limit: runs once more by itself")

    assert store.retry_spent("add-marker/1", "time limit")


def test_a_recorded_automatic_rework_is_kept_per_cause(tmp_path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])

    store.record_auto_rework("add-marker/1", AutoRework.E2E_FAILED)
    store.record_auto_rework("add-marker/1", AutoRework.PRODUCT_CODE)
    store.record_auto_rework("add-marker/1", AutoRework.E2E_FAILED)

    assert store.get("add-marker/1").auto_reworks == (
        AutoRework.E2E_FAILED,
        AutoRework.PRODUCT_CODE,
    ), "each cause once, however often it is recorded"


def test_an_automatic_rework_survives_a_requeue_a_replan_and_a_restart(tmp_path) -> None:
    path = tmp_path / "units.json"
    store = UnitStore(path)
    store.upsert([unit()])
    store.record_auto_rework("add-marker/1", AutoRework.E2E_FAILED)

    store.set_state("add-marker/1", UnitState.FAILED, note="e2e-test failed")
    store.set_state("add-marker/1", PLANNED, cause=Cause.REQUEUED, by=REQUEUE_BY)
    store.upsert([unit(title="new wording")])

    assert UnitStore(path).get("add-marker/1").auto_reworks == (AutoRework.E2E_FAILED,)


def test_a_stored_unit_written_before_the_record_existed_has_had_no_automatic_rework(
    tmp_path,
) -> None:
    path = tmp_path / "units.json"
    UnitStore(path).upsert([unit()])
    raw = json.loads(path.read_text())
    for record in raw["units"]:
        record.pop("auto_reworks", None)
    path.write_text(json.dumps(raw))
    store = UnitStore(path)
    assert store.get("add-marker/1").auto_reworks == ()

    store.record_auto_rework("add-marker/1", AutoRework.E2E_FAILED)

    assert UnitStore(path).get("add-marker/1").auto_reworks == (AutoRework.E2E_FAILED,)


def seed_two_changes(store: UnitStore) -> None:
    store.upsert(
        [stored_unit("feature/1", change="feature", groups=(1,))]
        + [stored_unit("other/1", change="other", groups=(1,))]
    )


def backing_ids(backing: InMemoryUnitsStore) -> list[str]:
    """What the backing store holds, read straight from it and not through `UnitStore`."""
    return [row.id for row in asyncio.run(backing.list())]


class RacingStore(InMemoryUnitsStore):
    """A stand-in on which another writer changes a unit just after the first listing made once
    `arm` has been called, and which answers that listing as it was before the change."""

    def __init__(self, racer: str) -> None:
        super().__init__()
        self.racer = racer
        self.armed = False
        self.raced = False

    def arm(self) -> None:
        self.armed = True

    async def list(self):  # noqa: ANN201
        listed = await super().list()
        if self.armed and not self.raced:
            self.raced = True
            await self.change_racer()
        return listed

    async def change_racer(self) -> None:
        current = await self.get(self.racer)
        assert current is not None
        body: dict[str, Any] = {**current.body, "estimated_lines": 777}
        await InMemoryUnitsStore.put_if(self, self.racer, body, current.version)


class LateRacingStore(RacingStore):
    """A stand-in on which the racer changes between the write's check and its `put_if`: every
    listing is true, and the writer's `put_if` for the racer finds it already moved."""

    async def list(self):  # noqa: ANN201
        return await InMemoryUnitsStore.list(self)

    async def put_if(self, unit_id, body, version, fence=None):  # noqa: ANN001, ANN201
        if self.armed and unit_id == self.racer and not self.raced:
            self.raced = True
            await self.change_racer()
        return await super().put_if(unit_id, body, version, fence)


class MidWriteStore(InMemoryUnitsStore):
    """A stand-in that runs `hook` at the start of the second listing after `arm`: between a
    change's read and its write."""

    def __init__(self) -> None:
        super().__init__()
        self.listings = 0
        self.hook: Callable[[], Awaitable[None]] | None = None

    def arm(self, hook: Callable[[], Awaitable[None]]) -> None:
        self.listings = 0
        self.hook = hook

    async def list(self):  # noqa: ANN201
        self.listings += 1
        if self.hook is not None and self.listings == 2:
            await self.hook()
        return await super().list()


def test_units_upserted_over_the_store_are_read_back_by_get_and_all(tmp_path: Path) -> None:
    backing = InMemoryUnitsStore()
    store = UnitStore(tmp_path / "units.json", store=backing)
    seed_two_changes(store)

    assert sorted(backing_ids(backing)) == ["feature/1", "other/1"]
    assert not (tmp_path / "units.json").exists()
    assert [u.id for u in store.all()] == ["feature/1", "other/1"]
    assert store.get("feature/1").change == "feature"


def test_a_state_change_over_the_store_is_seen_by_a_second_unit_store(tmp_path: Path) -> None:
    backing = InMemoryUnitsStore()
    first = UnitStore(tmp_path / "units.json", store=backing)
    seed_two_changes(first)

    first.set_state("feature/1", RUNNING, branch="spec/feature/1")

    held = asyncio.run(backing.get("feature/1"))
    assert held is not None
    assert held.body["state"] == RUNNING
    second = UnitStore(tmp_path / "other.json", store=backing)
    assert second.get("feature/1").state == RUNNING
    assert second.get("feature/1").branch == "spec/feature/1"
    assert second.get("other/1").state != RUNNING


def test_a_unit_that_is_not_stored_raises_key_error_over_the_store(tmp_path: Path) -> None:
    backing = InMemoryUnitsStore()
    store = UnitStore(tmp_path / "units.json", store=backing)
    seed_two_changes(store)
    assert backing_ids(backing) != []

    with pytest.raises(KeyError):
        store.get("missing/1")


def test_replace_if_unchanged_over_the_store_writes_the_differing_units(tmp_path: Path) -> None:
    backing = InMemoryUnitsStore()
    store = UnitStore(tmp_path / "units.json", store=backing)
    seed_two_changes(store)
    base = {u.id: u for u in store.all()}
    after = {**base, "feature/1": base["feature/1"].model_copy(update={"estimated_lines": 99})}
    after["feature/2"] = base["feature/1"].model_copy(update={"id": "feature/2"})

    moved = store.replace_if_unchanged(base, after)

    assert moved == []
    assert "feature/2" in backing_ids(backing)
    assert store.get("feature/1").estimated_lines == 99
    assert store.get("feature/2").id == "feature/2"
    assert store.get("other/1") == base["other/1"]


def test_replace_if_unchanged_over_the_store_writes_nothing_when_one_unit_moved(
    tmp_path: Path,
) -> None:
    backing = RacingStore("other/1")
    store = UnitStore(tmp_path / "units.json", store=backing)
    seed_two_changes(store)
    base = {u.id: u for u in store.all()}
    after = {
        **base,
        "feature/1": base["feature/1"].model_copy(update={"estimated_lines": 99}),
        "other/1": base["other/1"].model_copy(update={"estimated_lines": 55}),
    }
    backing.arm()

    moved = store.replace_if_unchanged(base, after)

    assert backing.raced
    assert moved == ["other/1"]
    assert store.get("feature/1") == base["feature/1"]
    assert store.get("other/1").estimated_lines == 777


def test_replace_if_unchanged_over_the_store_names_a_unit_that_moves_during_the_write(
    tmp_path: Path,
) -> None:
    backing = LateRacingStore("other/1")
    store = UnitStore(tmp_path / "units.json", store=backing)
    seed_two_changes(store)
    base = {u.id: u for u in store.all()}
    after = {
        **base,
        "feature/1": base["feature/1"].model_copy(update={"estimated_lines": 99}),
        "other/1": base["other/1"].model_copy(update={"estimated_lines": 55}),
    }
    backing.arm()

    moved = store.replace_if_unchanged(base, after)

    assert backing.raced
    assert moved == ["other/1"]
    assert store.get("other/1").estimated_lines == 777


def test_a_read_without_the_lock_does_not_hide_a_write_made_by_another_host(
    tmp_path: Path,
) -> None:
    backing = MidWriteStore()
    store = UnitStore(tmp_path / "units.json", store=backing)
    seed_two_changes(store)

    async def another_host_writes_then_this_one_reads() -> None:
        current = await backing.get("feature/1")
        assert current is not None
        body: dict[str, Any] = {**current.body, "estimated_lines": 777}
        await backing.put_if("feature/1", body, current.version)
        await asyncio.to_thread(store.get, "feature/1")

    backing.arm(another_host_writes_then_this_one_reads)

    with pytest.raises(VersionConflict):
        store.set_state("feature/1", RUNNING, branch="spec/feature/1")

    assert store.get("feature/1").estimated_lines == 777
    assert store.get("feature/1").state != RUNNING


def test_with_no_store_the_file_is_the_store_and_a_given_store_replaces_it(tmp_path: Path) -> None:
    path = tmp_path / "units.json"
    plain = UnitStore(path)
    seed_two_changes(plain)
    plain.set_state("feature/1", RUNNING, branch="spec/feature/1")
    assert UnitStore(path).get("feature/1").state == RUNNING

    over_empty_store = UnitStore(path, store=InMemoryUnitsStore())

    assert over_empty_store.all() == []
    assert [u.id for u in UnitStore(path).all()] == ["feature/1", "other/1"]


FLOOR_REASON = "full floor, group 1: contract"


def test_a_units_floor_reason_and_raise_round_trip_and_empty_ones_are_left_out_of_the_record(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            app_unit("add-marker/1", floor_reason=FLOOR_REASON, raised_from="light"),
            app_unit("add-marker/2"),
        ]
    )

    reloaded = UnitStore(store.path)
    written = {r["id"]: r for r in json.loads(store.path.read_text())["units"]}
    assert reloaded.get("add-marker/1").floor_reason == FLOOR_REASON
    assert reloaded.get("add-marker/1").raised_from == "light"
    assert reloaded.get("add-marker/2").floor_reason == ""
    assert reloaded.get("add-marker/2").raised_from == ""
    assert written["add-marker/1"]["floor_reason"] == FLOOR_REASON
    assert written["add-marker/1"]["raised_from"] == "light"
    assert "floor_reason" not in written["add-marker/2"]
    assert "raised_from" not in written["add-marker/2"]


def test_a_replan_gives_an_unstarted_unit_its_new_floor_and_a_started_one_keeps_its_own(
    tmp_path: Path,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            app_unit("add-marker/1", floor_reason=FLOOR_REASON, raised_from="light"),
            app_unit("add-marker/2", floor_reason=FLOOR_REASON, raised_from="light"),
        ]
    )
    store.set_state("add-marker/1", RUNNING)

    store.upsert([app_unit("add-marker/1"), app_unit("add-marker/2")], change="add-marker")

    assert store.get("add-marker/1").floor_reason == FLOOR_REASON
    assert store.get("add-marker/1").raised_from == "light"
    assert store.get("add-marker/2").floor_reason == ""
    assert store.get("add-marker/2").raised_from == ""
