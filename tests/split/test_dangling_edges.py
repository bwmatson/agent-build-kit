"""An edge that would point at nothing is an error naming it, found before any write."""

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Member
from agent_build_kit.split.copy import CopyRefused, carry_out, preflight
from agent_build_kit.split.select import plan_split
from tests.factories import new_unit
from tests.split_sources import snapshot_tree, source_installation, write_change, write_units


def installations(tmp_path):
    destination = source_installation(tmp_path / "destination")
    source = source_installation(tmp_path / "source")
    write_change(source, "moves", ["app", "app"])
    write_change(source, "stays", ["lib"])
    return source, destination


def test_a_dependency_on_a_unit_that_stays_is_an_error_naming_unit_field_and_target(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged"),
        new_unit("moves/2", state="merged", depends_on=("moves/1", "stays/1")),
        new_unit("stays/1", repo="lib", state="merged"),
    )
    before = snapshot_tree(destination.root)

    with pytest.raises(CopyRefused) as refused:
        carry_out(source, destination, plan_split(source, "app"))

    (error,) = refused.value.errors
    assert all(word in error for word in ("moves/2", "depends_on", "stays/1"))
    assert snapshot_tree(destination.root) == before


def test_every_dangling_edge_is_listed_with_nothing_written(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged", depends_on=("stays/1",), needs=("stays/1",)),
        new_unit("moves/2", state="merged", depends_on=("stays/2",)),
        new_unit("stays/1", repo="lib", state="merged"),
        new_unit("stays/2", repo="lib", state="merged"),
    )
    before = snapshot_tree(destination.root)

    found = preflight(source, destination, plan_split(source, "app"))

    assert len(found.errors) == 3
    fields = {(e.split()[1], "needs" in e, "depends_on" in e) for e in found.errors}
    assert fields == {("moves/1", True, False), ("moves/1", False, True), ("moves/2", False, True)}
    assert snapshot_tree(destination.root) == before


def test_a_joined_member_that_is_neither_moved_nor_in_the_destination_is_an_error(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged", joined=(Member(change="elsewhere", groups=(1,)),)),
    )
    # A spanning unit blocks the plan itself; the check still holds a plan that selects it.
    plan = plan_split(source, "app").model_copy(update={"units_moved": ("moves/1",)})

    found = preflight(source, destination, plan)

    (error,) = found.errors
    assert all(word in error for word in ("moves/1", "joined", "elsewhere"))


def test_a_target_already_in_the_destination_is_fine(tmp_path):
    source, destination = installations(tmp_path)
    write_units(destination, new_unit("base/1", repo="lib", state="merged"))
    write_units(
        source,
        new_unit("moves/1", state="merged", depends_on=("base/1",), needs=("base/1",)),
    )

    carry_out(source, destination, plan_split(source, "app"))

    assert [u.id for u in UnitStore(destination.state_dir / "units.json").all()] == [
        "base/1",
        "moves/1",
    ]


def test_a_needs_line_in_a_moved_tasks_file_whose_change_stays_is_an_error(tmp_path):
    source, destination = installations(tmp_path)
    write_change(source, "other", ["lib", "lib"])
    tasks = source.changes_dir / "moves" / "tasks.md"
    tasks.write_text(tasks.read_text() + "\nNeeds: other group 2\n")

    found = preflight(source, destination, plan_split(source, "app"))

    (error,) = found.errors
    assert all(word in error for word in ("moves", "group 2", "other"))


def test_a_staying_edge_into_the_moved_set_is_a_warning_and_with_remove_an_error(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged"),
        new_unit("stays/1", repo="lib", state="merged", depends_on=("moves/1",)),
    )
    plan = plan_split(source, "app")

    kept = preflight(source, destination, plan)
    removing = preflight(source, destination, plan, remove=True)

    assert kept.errors == ()
    (warning,) = kept.warnings
    assert all(word in warning for word in ("stays/1", "depends_on", "moves/1"))
    (error,) = removing.errors
    assert all(word in error for word in ("stays/1", "depends_on", "moves/1"))


def test_a_staying_changes_needs_line_naming_a_moved_change_is_a_warning_and_with_remove_an_error(
    tmp_path,
):
    source, destination = installations(tmp_path)
    tasks = source.changes_dir / "stays" / "tasks.md"
    tasks.write_text(tasks.read_text() + "\nNeeds: moves group 1\n")
    plan = plan_split(source, "app")

    kept = preflight(source, destination, plan)
    removing = preflight(source, destination, plan, remove=True)

    assert kept.errors == ()
    (warning,) = kept.warnings
    assert all(word in warning for word in ("stays", "moves", "group 1"))
    (error,) = removing.errors
    assert all(word in error for word in ("stays", "moves", "group 1"))


def test_a_needs_line_naming_an_archived_change_is_not_dangling(tmp_path):
    source, destination = installations(tmp_path)
    write_change(source, "done", ["lib"], archived="2026-01-01")
    tasks = source.changes_dir / "moves" / "tasks.md"
    tasks.write_text(tasks.read_text() + "\nNeeds: done group 1\n")

    found = preflight(source, destination, plan_split(source, "app"))

    assert found.errors == ()
