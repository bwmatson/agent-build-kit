"""The dependency check knows archive entries and the changes of units with no directory."""

from agent_build_kit.pipeline.units import Member
from agent_build_kit.split.copy import preflight
from agent_build_kit.split.select import plan_split
from tests.factories import new_unit
from tests.split_sources import source_installation, write_change, write_units

ARCHIVED = "2026-01-05"


def installations(tmp_path):
    destination = source_installation(tmp_path / "destination")
    source = source_installation(tmp_path / "source")
    write_change(source, "moves", ["app", "app"])
    return source, destination


def test_a_joined_member_that_is_a_moved_archive_entry_and_a_dependency_on_its_unit_are_fine(
    tmp_path,
):
    source, destination = installations(tmp_path)
    write_change(source, "done", ["app"], archived=ARCHIVED)
    write_units(
        source,
        new_unit("done/1", state="merged"),
        new_unit(
            "moves/1",
            state="merged",
            depends_on=("done/1",),
            joined=(Member(change="done", groups=(1,)),),
        ),
    )

    found = preflight(source, destination, plan_split(source, "app"))

    assert found.errors == ()


def test_a_joined_member_that_is_an_archive_entry_of_the_destination_is_fine(tmp_path):
    source, destination = installations(tmp_path)
    write_change(destination, "old", ["lib"], archived=ARCHIVED)
    write_units(
        source,
        new_unit("moves/1", state="merged", joined=(Member(change="old", groups=(1,)),)),
    )

    found = preflight(source, destination, plan_split(source, "app"))

    assert found.errors == ()


def test_a_joined_member_that_is_a_no_directory_change_of_another_moved_unit_is_fine(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("gone/1", repo="app", state="merged"),
        new_unit("moves/1", state="merged", joined=(Member(change="gone", groups=(1,)),)),
    )
    plan = plan_split(source, "app")

    found = preflight(source, destination, plan)

    assert plan.units_moved_no_directory == ("gone/1",)
    assert found.errors == ()


def test_a_joined_member_that_is_a_staying_archive_entry_is_the_only_joined_error(tmp_path):
    source, destination = installations(tmp_path)
    write_change(source, "done", ["app"], archived=ARCHIVED)
    write_change(source, "kept", ["lib"], archived=ARCHIVED)
    write_units(
        source,
        new_unit(
            "moves/1",
            state="merged",
            joined=(Member(change="done", groups=(1,)), Member(change="kept", groups=(1,))),
        ),
    )
    # A spanning unit blocks the plan itself; the check still holds a plan that selects it.
    plan = plan_split(source, "app").model_copy(update={"units_moved": ("moves/1",)})

    found = preflight(source, destination, plan)

    (error,) = found.errors
    assert all(word in error for word in ("moves/1", "joined", "kept"))


def test_a_joined_member_with_no_directory_anywhere_of_a_unit_that_moves_is_fine(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged", joined=(Member(change="gone", groups=(1,)),)),
    )
    plan = plan_split(source, "app")

    found = preflight(source, destination, plan)

    assert plan.units_moved_active == ("moves/1",)
    assert found.errors == ()
