"""A dependency on a merged unit that stays for a kept mixed change or another project is
dropped like one of another repo, with its reason; every other staying target still refuses."""

from datetime import UTC, datetime

import pytest

from agent_build_kit.pipeline import loaded_code
from agent_build_kit.pipeline.loaded_code import LoadedCode, TickRecord
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Member, base_of, waiting_on
from agent_build_kit.split.copy import (
    DroppedEdge,
    EdgeReason,
    carry_out,
    dropped_edges,
    outstanding,
    preflight,
)
from agent_build_kit.split.remove import verify
from agent_build_kit.split.select import RefusalKind, plan_split
from tests.factories import new_unit, started_ids
from tests.split_sources import snapshot_tree, source_installation, write_change, write_units

TICK = 5
UNTAGGED = "# Tasks\n\n## 1. No tag here\n\n- [ ] 1.1 Test: x\n"


@pytest.fixture(autouse=True)
def tick():
    loaded_code.running_tick(TickRecord(number=TICK, started_at=datetime(2026, 1, 1, tzinfo=UTC)))
    yield
    loaded_code.running_tick(None)


def installations(tmp_path, **projects):
    """A moved `app` change `g` and a mixed change `m` whose group 4 is of `app`."""
    destination = source_installation(tmp_path / "destination", **projects)
    source = source_installation(tmp_path / "source", **projects)
    write_change(source, "g", ["app", "app"])
    write_change(source, "m", ["app", "lib", "app", "app"])
    return source, destination


def kept(uid="m/4", **overrides):
    return new_unit(uid, **{"repo": "app", "state": "merged", **overrides})


def dependent(*targets, **overrides):
    return new_unit("g/1", depends_on=targets, **overrides)


def refused_next_to_a_dropped_edge(tmp_path, bad, *, extra=()):
    """The preflight of `g/1` depending on a merged kept unit `m/3` and on `bad`."""
    source, destination = installations(tmp_path)
    write_units(source, dependent("m/3", bad.id), kept("m/3"), bad, *extra)
    return preflight(source, destination, plan_split(source, "app", allow_mixed="source"))


def test_a_merged_unit_of_a_kept_mixed_change_is_dropped_from_all_three_lists(tmp_path):
    source, destination = installations(tmp_path)
    original = new_unit(
        "g/1",
        depends_on=("m/4", "g/2"),
        needs=("m/4", "g/2"),
        merge_needs=("m/4", "g/2"),
    )
    write_units(source, original, new_unit("g/2", state="merged"), kept())
    plan = plan_split(source, "app", allow_mixed="source")
    before = snapshot_tree(source.root)

    found = preflight(source, destination, plan)
    carry_out(source, destination, plan)

    assert found.errors == ()
    assert set(found.dropped) == {
        DroppedEdge(unit="g/1", field="depends_on", target="m/4", reason=EdgeReason.KEPT_CHANGE),
        DroppedEdge(unit="g/1", field="needs", target="m/4", reason=EdgeReason.KEPT_CHANGE),
    }
    written = UnitStore(destination.state_dir / "units.json").get("g/1")
    assert written == original.model_copy(
        update={"depends_on": ("g/2",), "needs": ("g/2",), "merge_needs": ("g/2",)}
    )
    assert snapshot_tree(source.root) == before


@pytest.mark.parametrize("state", ["in_review", "failed", "closed", "satisfied"])
def test_a_kept_unit_that_is_not_merged_is_the_dangling_error(tmp_path, state):
    found = refused_next_to_a_dropped_edge(tmp_path, kept("m/4", state=state))

    (error,) = found.errors
    assert all(word in error for word in ("g/1", "depends_on", "m/4"))
    assert [(e.target, e.reason) for e in found.dropped] == [("m/3", EdgeReason.KEPT_CHANGE)]


def test_a_kept_unit_merged_at_or_after_the_loaded_tick_says_to_run_a_tick(tmp_path):
    found = refused_next_to_a_dropped_edge(tmp_path, kept("m/4", merged_tick=TICK))

    (error,) = found.errors
    assert all(word in error for word in ("g/1", "m/4", "tick"))
    assert [e.target for e in found.dropped] == ["m/3"]


def test_a_superseded_by_naming_a_kept_unit_is_the_dangling_error(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        dependent("m/3", state="closed", superseded_by=("m/4",)),
        kept("m/3"),
        kept(),
    )

    found = preflight(source, destination, plan_split(source, "app", allow_mixed="source"))

    (error,) = found.errors
    assert all(word in error for word in ("g/1", "superseded_by", "m/4"))
    assert [e.target for e in found.dropped] == ["m/3"]


def test_the_side_decides_whether_the_kept_unit_is_dropped_or_moves(tmp_path):
    source, destination = installations(tmp_path)
    write_units(source, dependent("m/4"), kept())

    unsided = plan_split(source, "app")
    keeping = plan_split(source, "app", allow_mixed="source")
    moving = plan_split(source, "app", allow_mixed="destination", destination_repos={"app", "lib"})

    assert {refusal.kind for refusal in unsided.refusals} == {RefusalKind.MIXED}
    assert [e.reason for e in preflight(source, destination, unsided).dropped] == [
        EdgeReason.KEPT_CHANGE
    ]
    assert [e.reason for e in preflight(source, destination, keeping).dropped] == [
        EdgeReason.KEPT_CHANGE
    ]
    assert {"g/1", "m/4"} <= set(moving.units_moved)
    found = preflight(source, destination, moving)
    assert (found.errors, found.dropped) == ((), ())


def test_the_unit_of_an_unreadable_change_is_the_dangling_error(tmp_path):
    source, destination = installations(tmp_path)
    write_change(source, "broken", ["app"]).joinpath("tasks.md").write_text(UNTAGGED)
    write_units(
        source,
        dependent("m/3", "broken/1"),
        kept("m/3"),
        new_unit("broken/1", repo="app", state="merged"),
    )
    plan = plan_split(source, "app", allow_mixed="source")

    found = preflight(source, destination, plan)

    assert [item.name for item in plan.changes_unreadable] == ["broken"]
    (error,) = found.errors
    assert all(word in error for word in ("g/1", "depends_on", "broken/1"))
    assert [e.target for e in found.dropped] == ["m/3"]


def test_a_spanning_unit_is_the_dangling_error(tmp_path):
    source, destination = installations(tmp_path)
    spanning = kept("m/4", joined=(Member(change="g", groups=(2,)),))
    write_units(source, dependent("m/3", "m/4"), kept("m/3"), spanning)
    plan = plan_split(source, "app", allow_mixed="source")

    found = preflight(source, destination, plan)

    assert "m/4" in plan.units_blocking
    assert any(all(word in e for word in ("g/1", "depends_on", "m/4")) for e in found.errors)
    assert [e.target for e in found.dropped] == ["m/3"]


def test_a_unit_of_an_unclassified_archive_entry_is_the_dangling_error(tmp_path):
    source, destination = installations(tmp_path)
    write_change(source, "bare", ["app"], archived="2026-01-04", tasks=False)
    write_units(
        source,
        dependent("m/3", "bare/1"),
        kept("m/3"),
        new_unit("bare/1", repo="app", state="merged"),
    )
    plan = plan_split(source, "app", allow_mixed="source")

    found = preflight(source, destination, plan)

    assert plan.archive_unclassified == ("2026-01-04-bare",)
    (error,) = found.errors
    assert all(word in error for word in ("g/1", "depends_on", "bare/1"))
    assert [e.target for e in found.dropped] == ["m/3"]


def test_a_merged_unit_of_another_project_is_dropped_with_project_only_when_one_is_named(tmp_path):
    destination = source_installation(tmp_path / "destination", app=["web", "api"])
    source = source_installation(tmp_path / "source", app=["web", "api"])
    write_change(source, "w", ["app/web"])
    write_change(source, "p", ["app/api"])
    write_units(
        source,
        new_unit("w/1", depends_on=("p/1",), project="web"),
        new_unit("p/1", repo="app", project="api", state="merged"),
    )

    named = preflight(source, destination, plan_split(source, "app", project="web"))
    whole = plan_split(source, "app")
    unnamed = preflight(source, destination, whole)

    assert named.errors == ()
    assert [(e.unit, e.target, e.reason) for e in named.dropped] == [
        ("w/1", "p/1", EdgeReason.PROJECT)
    ]
    assert "p/1" in whole.units_moved
    assert (unnamed.errors, unnamed.dropped) == ((), ())


def test_a_unit_of_another_repo_takes_the_repo_reason_even_in_a_kept_change(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        dependent("other/1", "m/2", "m/3"),
        new_unit("other/1", repo="lib", state="merged"),
        new_unit("m/2", repo="lib", state="merged"),
        kept("m/3"),
    )

    found = preflight(source, destination, plan_split(source, "app", allow_mixed="source"))

    assert found.errors == ()
    assert {(e.target, e.reason) for e in found.dropped} == {
        ("other/1", EdgeReason.REPO),
        ("m/2", EdgeReason.REPO),
        ("m/3", EdgeReason.KEPT_CHANGE),
    }


def test_the_destination_reads_the_unit_as_one_with_no_dependency_on_the_kept_unit(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("g/1", depends_on=("m/4",), needs=("m/4",), merge_needs=("m/4",)),
        kept(),
    )
    plan = plan_split(source, "app", allow_mixed="source")
    loaded = LoadedCode(number=TICK)

    carry_out(source, destination, plan)
    here = UnitStore(destination.state_dir / "units.json").all()
    there = UnitStore(source.state_dir / "units.json").all()

    (moved,) = (u for u in here if u.id == "g/1")
    (original,) = (u for u in there if u.id == "g/1")
    assert waiting_on(moved, here, loaded) == []
    assert waiting_on(original, there, loaded) == []
    assert base_of(moved, here) == base_of(original, there)
    assert started_ids(here) == ["g/1"]
    assert original.depends_on == ("m/4",)


def test_a_second_run_writes_nothing_and_the_copy_verifies(tmp_path):
    source, destination = installations(tmp_path)
    write_units(source, dependent("m/4"), kept())
    plan = plan_split(source, "app", allow_mixed="source")
    carry_out(source, destination, plan)
    before = snapshot_tree(destination.root)

    carry_out(source, destination, plan)

    assert snapshot_tree(destination.root) == before
    assert not outstanding(source, destination, plan)
    assert verify(source, destination, plan) == []
    assert [e.reason for e in dropped_edges(source, destination, plan)] == [EdgeReason.KEPT_CHANGE]
