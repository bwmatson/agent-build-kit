"""A dependency on a merged unit of another repo is carried as satisfied history."""

from datetime import UTC, datetime

import pytest

from agent_build_kit.pipeline import loaded_code
from agent_build_kit.pipeline.loaded_code import LoadedCode, TickRecord
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import waiting_on
from agent_build_kit.split import scrubbing
from agent_build_kit.split.copy import (
    CopyRefused,
    DroppedEdge,
    carry_out,
    dropped_edges,
    outstanding,
    preflight,
)
from agent_build_kit.split.remove import verify
from agent_build_kit.split.select import plan_split
from tests.factories import new_unit, started_ids
from tests.split_sources import snapshot_tree, source_installation, write_change, write_units

TERM = "secret-term"
TICK = 5


@pytest.fixture(autouse=True)
def tick():
    loaded_code.running_tick(TickRecord(number=TICK, started_at=datetime(2026, 1, 1, tzinfo=UTC)))
    yield
    loaded_code.running_tick(None)


def installations(tmp_path):
    destination = source_installation(tmp_path / "destination")
    source = source_installation(tmp_path / "source")
    write_change(source, "moves", ["app", "app"])
    write_change(source, "stays", ["lib"])
    return source, destination


def foreign(uid="other/1", **overrides):
    return new_unit(uid, repo="lib", state="merged", **overrides)


def moved_with(dependencies):
    return new_unit("moves/2", depends_on=dependencies)


def test_a_merged_foreign_edge_is_dropped_from_all_three_lists_and_reported(tmp_path):
    source, destination = installations(tmp_path)
    original = new_unit(
        "moves/2",
        depends_on=("other/1", "moves/1"),
        needs=("other/1", "moves/1"),
        merge_needs=("other/1",),
    )
    write_units(source, new_unit("moves/1", state="merged"), original, foreign())
    plan = plan_split(source, "app")
    before = snapshot_tree(source.root)

    found = preflight(source, destination, plan)
    carry_out(source, destination, plan)

    assert found.errors == ()
    assert set(found.dropped) == {
        DroppedEdge(unit="moves/2", field="depends_on", target="other/1"),
        DroppedEdge(unit="moves/2", field="needs", target="other/1"),
    }
    assert dropped_edges(source, destination, plan) == found.dropped
    written = UnitStore(destination.state_dir / "units.json").get("moves/2")
    assert written == original.model_copy(
        update={"depends_on": ("moves/1",), "needs": ("moves/1",), "merge_needs": ()}
    )
    assert snapshot_tree(source.root) == before


@pytest.mark.parametrize("state", ["in_review", "failed", "closed", "satisfied"])
def test_a_foreign_unit_that_is_not_merged_is_the_dangling_error(tmp_path, state):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged"),
        moved_with(("other/1", "bad/1")),
        foreign(),
        new_unit("bad/1", repo="lib", state=state),
    )

    found = preflight(source, destination, plan_split(source, "app"))

    (error,) = found.errors
    assert all(word in error for word in ("moves/2", "depends_on", "bad/1"))
    assert [edge.target for edge in found.dropped] == ["other/1"]


def test_a_merged_foreign_unit_whose_merge_is_not_loaded_says_to_run_a_tick(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        moved_with(("other/1", "late/1")),
        foreign(merged_tick=1),
        foreign("late/1", merged_tick=TICK),
    )

    found = preflight(source, destination, plan_split(source, "app"))

    (error,) = found.errors
    assert all(word in error for word in ("moves/2", "late/1", "tick"))
    assert [edge.target for edge in found.dropped] == ["other/1"]


def test_a_staying_unit_of_the_moving_repo_a_superseded_by_target_and_a_stranger_refuse(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit(
            "moves/2",
            state="closed",
            depends_on=("other/1", "stays/1", "ghost/1"),
            superseded_by=("other/2",),
        ),
        foreign(),
        foreign("other/2"),
        new_unit("stays/1", repo="app", state="merged"),
    )

    found = preflight(source, destination, plan_split(source, "app"))

    assert len(found.errors) == 3
    for words in (
        ("moves/2", "depends_on", "stays/1"),
        ("moves/2", "depends_on", "ghost/1"),
        ("moves/2", "superseded_by", "other/2"),
    ):
        assert any(all(word in error for word in words) for error in found.errors)
    assert [edge.target for edge in found.dropped] == ["other/1"]


def test_a_foreign_unit_already_in_the_destination_is_kept_and_not_reported(tmp_path):
    source, destination = installations(tmp_path)
    write_units(destination, foreign())
    write_units(source, moved_with(("other/1", "other/2")), foreign(), foreign("other/2"))
    plan = plan_split(source, "app")

    found = preflight(source, destination, plan)
    carry_out(source, destination, plan)

    assert found.errors == ()
    assert [edge.target for edge in found.dropped] == ["other/2"]
    written = UnitStore(destination.state_dir / "units.json").get("moves/2")
    assert written.depends_on == ("other/1",)


def test_a_second_run_finds_the_dropped_edge_record_equal_and_writes_nothing(tmp_path):
    source, destination = installations(tmp_path)
    write_units(source, moved_with(("other/1",)), foreign())
    plan = plan_split(source, "app")
    carry_out(source, destination, plan)
    before = snapshot_tree(destination.root)

    carry_out(source, destination, plan)

    assert snapshot_tree(destination.root) == before
    assert not outstanding(source, destination, plan)
    assert verify(source, destination, plan) == []


def test_scrubbing_touches_the_dropped_edge_record_and_no_ids(tmp_path, monkeypatch):
    source, destination = installations(tmp_path)
    monkeypatch.setattr(scrubbing, "terms_for", lambda installation, *, target=None: [TERM])
    monkeypatch.setattr(
        scrubbing, "scrub_text", lambda text, terms: text.replace(TERM, "<redacted>")
    )
    write_units(
        source,
        new_unit("moves/1", state="merged"),
        new_unit("moves/2", depends_on=("other/1", "moves/1"), feedback=f"fix {TERM}"),
        foreign(),
    )
    plan = plan_split(source, "app")

    carry_out(source, destination, plan, scrub=True)

    written = UnitStore(destination.state_dir / "units.json").get("moves/2")
    assert (written.id, written.depends_on, written.feedback) == (
        "moves/2",
        ("moves/1",),
        "fix <redacted>",
    )
    assert verify(source, destination, plan, scrub=True) == []
    assert not outstanding(source, destination, plan, scrub=True)


def test_the_moved_unit_waits_on_nothing_for_the_dropped_edge_and_can_start(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged"),
        new_unit("moves/2", depends_on=("other/1", "moves/1")),
        foreign(),
    )
    loaded = LoadedCode(number=TICK)
    carry_out(source, destination, plan_split(source, "app"))

    in_source = UnitStore(source.state_dir / "units.json").all()
    graph = UnitStore(destination.state_dir / "units.json").all()

    (here,) = (unit for unit in graph if unit.id == "moves/2")
    (there,) = (unit for unit in in_source if unit.id == "moves/2")
    assert waiting_on(there, in_source, loaded) == []
    assert waiting_on(here, graph, loaded) == []
    assert "moves/2" in started_ids(graph)


def test_an_unmerged_foreign_parent_is_refused_rather_than_copied(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        moved_with(("other/1",)),
        new_unit("other/1", repo="lib", state="in_review"),
    )
    before = snapshot_tree(destination.root)

    with pytest.raises(CopyRefused):
        carry_out(source, destination, plan_split(source, "app"))

    assert snapshot_tree(destination.root) == before
