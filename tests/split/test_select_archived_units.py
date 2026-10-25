"""Units of archive entries move with the entry, matched to it by the change's name."""

from agent_build_kit.pipeline.units import Member
from agent_build_kit.split.select import RefusalKind, plan_split
from tests.factories import new_unit
from tests.split_sources import source_installation, write_change, write_units


def source_with_archive_entries(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "done", ["app"], archived="2026-01-05")
    write_change(source, "other", ["lib"], archived="2026-01-06")
    return source


def test_units_of_a_moved_archive_entry_are_selected_and_those_of_a_staying_one_are_not(tmp_path):
    source = source_with_archive_entries(tmp_path)
    write_units(
        source,
        new_unit("done/1", state="merged"),
        new_unit("done/2", state="merged"),
        new_unit("other/1", repo="lib", state="merged"),
    )

    plan = plan_split(source, "app")

    assert plan.units_moved == ("done/1", "done/2")
    assert plan.units_moved_archived == ("done/1", "done/2")
    assert plan.units_staying == ("other/1",)
    assert plan.refusals == ()


def test_a_unit_of_an_archive_entry_with_a_staying_member_is_the_spanning_error(tmp_path):
    source = source_with_archive_entries(tmp_path)
    write_change(source, "stays", ["lib"])
    write_units(
        source,
        new_unit("done/1", state="merged", joined=(Member(change="stays", groups=(1,)),)),
    )

    plan = plan_split(source, "app")

    (refusal,) = plan.refusals
    assert refusal.kind == RefusalKind.SPANNING_UNIT
    assert all(name in refusal.line for name in ("done/1", "done", "stays"))
    assert plan.units_blocking == ("done/1",)
    assert plan.units_moved == ()


def test_units_of_an_archive_entry_and_of_an_active_change_both_move(tmp_path):
    source = source_with_archive_entries(tmp_path)
    write_change(source, "live", ["app"])
    write_units(source, new_unit("done/1", state="merged"), new_unit("live/1", state="merged"))

    plan = plan_split(source, "app")

    assert plan.units_moved == ("done/1", "live/1")
    assert plan.units_moved_active == ("live/1",)
    assert plan.units_moved_archived == ("done/1",)


def test_a_held_unit_of_an_archive_entry_is_the_in_flight_error_naming_the_state(tmp_path):
    source = source_with_archive_entries(tmp_path)
    write_units(source, new_unit("done/1", state="held"))

    plan = plan_split(source, "app")

    (refusal,) = plan.refusals
    assert refusal.kind == RefusalKind.IN_FLIGHT_UNIT
    assert "done/1" in refusal.line
    assert "held" in refusal.line
    assert plan.units_blocking == ("done/1",)


def test_a_mixed_archive_entrys_units_follow_the_side_named(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "both", ["app", "lib"], archived="2026-01-05")
    write_units(source, new_unit("both/1", state="merged"))

    destination = plan_split(
        source, "app", allow_mixed="destination", destination_repos={"app", "lib"}
    )
    kept = plan_split(source, "app", allow_mixed="source")
    unnamed = plan_split(source, "app")

    assert destination.archive_moved == ("2026-01-05-both",)
    assert destination.units_moved == ("both/1",)
    assert kept.units_moved == ()
    assert kept.units_staying == ("both/1",)
    assert unnamed.units_moved == ()
    assert [refusal.kind for refusal in unnamed.refusals] == [RefusalKind.MIXED]


def test_a_change_name_whose_directories_disagree_refuses_its_unit(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "again", ["app"], archived="2026-01-05")
    write_change(source, "again", ["lib"])
    write_units(source, new_unit("again/1", state="merged"))

    plan = plan_split(source, "app")

    (refusal,) = plan.refusals
    assert refusal.kind == RefusalKind.AMBIGUOUS_CHANGE
    assert "again/1" in refusal.line
    assert "again" in refusal.line
    assert plan.units_moved == ()
