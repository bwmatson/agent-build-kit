"""A unit whose change has no directory moves by its repo, and the plan partitions the units."""

from agent_build_kit.pipeline.units import Member
from agent_build_kit.split.select import RefusalKind, plan_split
from tests.factories import new_unit
from tests.split_sources import source_installation, write_change, write_units


def test_a_unit_with_no_change_directory_moves_with_its_repo(tmp_path):
    source = source_installation(tmp_path)
    write_units(
        source,
        new_unit("gone/1", repo="app", state="merged"),
        new_unit("lost/1", repo="lib", state="merged"),
    )

    plan = plan_split(source, "app")

    assert plan.units_moved == ("gone/1",)
    assert plan.units_moved_no_directory == ("gone/1",)
    assert plan.units_staying == ("lost/1",)
    assert plan.refusals == ()


def test_with_a_project_only_that_projects_units_move(tmp_path):
    source = source_installation(tmp_path, app=["web"])
    write_units(
        source,
        new_unit("gone/1", repo="app", project="web", state="merged"),
        new_unit("gone/2", repo="app", project=".", state="merged"),
    )

    plan = plan_split(source, "app", project="web")

    assert plan.units_moved_no_directory == ("gone/1",)
    assert plan.units_staying == ("gone/2",)


def test_a_held_unit_with_no_directory_is_the_in_flight_error(tmp_path):
    source = source_installation(tmp_path)
    write_units(source, new_unit("gone/1", repo="app", state="held"))

    plan = plan_split(source, "app")

    (refusal,) = plan.refusals
    assert refusal.kind == RefusalKind.IN_FLIGHT_UNIT
    assert "gone/1" in refusal.line
    assert plan.units_blocking == ("gone/1",)


def test_a_unit_with_no_directory_and_a_staying_member_is_the_spanning_error(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "stays", ["lib"])
    joined = (Member(change="stays", groups=(1,)),)
    write_units(source, new_unit("gone/1", repo="app", state="merged", joined=joined))

    plan = plan_split(source, "app")

    (refusal,) = plan.refusals
    assert refusal.kind == RefusalKind.SPANNING_UNIT
    assert all(name in refusal.line for name in ("gone/1", "gone", "stays"))


def test_a_unit_with_no_directory_and_a_moving_member_is_selected(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "moves", ["app"])
    joined = (Member(change="moves", groups=(1,)),)
    write_units(source, new_unit("gone/1", repo="app", state="merged", joined=joined))

    plan = plan_split(source, "app")

    assert plan.units_moved == ("gone/1",)
    assert plan.refusals == ()


def test_the_units_are_partitioned_by_where_they_came_from(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "active", ["app"])
    write_change(source, "arch", ["app"], archived="2026-01-05")
    write_change(source, "stays", ["lib"])
    write_units(
        source,
        *(new_unit(f"active/{n}", state="merged") for n in (1, 2)),
        *(new_unit(f"arch/{n}", state="merged") for n in (1, 2, 3)),
        new_unit("gone/1", repo="app", state="merged"),
        *(new_unit(f"stays/{n}", repo="lib", state="merged") for n in (1, 2, 3, 4)),
    )

    plan = plan_split(source, "app")

    assert len(plan.units_moved_active) == 2
    assert len(plan.units_moved_archived) == 3
    assert len(plan.units_moved_no_directory) == 1
    union = (*plan.units_moved_active, *plan.units_moved_archived, *plan.units_moved_no_directory)
    assert sorted(union) == list(plan.units_moved)
    assert plan.units_staying == ("stays/1", "stays/2", "stays/3", "stays/4")
