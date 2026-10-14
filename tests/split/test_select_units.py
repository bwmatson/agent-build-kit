"""Which unit records a split moves, and which block it."""

import pytest

from agent_build_kit.pipeline.units import Member
from agent_build_kit.split.select import RefusalKind, plan_split
from tests.factories import new_unit
from tests.split_sources import source_installation, write_change, write_units


def source_with_a_moved_and_a_staying_change(tmp_path):
    source = source_installation(tmp_path)
    write_change(source, "moves", ["app", "app"])
    write_change(source, "stays", ["lib"])
    return source


def test_units_of_moved_changes_are_selected_and_others_are_not(tmp_path):
    source = source_with_a_moved_and_a_staying_change(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged"),
        new_unit("moves/2", state="merged"),
        new_unit("stays/1", repo="lib", state="merged"),
    )

    plan = plan_split(source, "app")

    assert plan.units_moved == ("moves/1", "moves/2")
    assert plan.units_blocking == ()


def test_a_unit_carrying_a_member_of_a_staying_change_is_an_error_naming_both_changes(tmp_path):
    source = source_with_a_moved_and_a_staying_change(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged", joined=(Member(change="stays", groups=(1,)),)),
    )

    plan = plan_split(source, "app")

    (refusal,) = plan.refusals
    assert refusal.kind == RefusalKind.SPANNING_UNIT
    assert all(name in refusal.line for name in ("moves/1", "moves", "stays"))
    assert plan.units_blocking == ("moves/1",)
    assert "moves/1" not in plan.units_moved


@pytest.mark.parametrize("state", ["running", "in_review", "held"])
def test_a_unit_in_flight_is_an_error_naming_its_state(tmp_path, state):
    source = source_with_a_moved_and_a_staying_change(tmp_path)
    write_units(source, new_unit("moves/1", state=state))

    plan = plan_split(source, "app")

    (refusal,) = plan.refusals
    assert refusal.kind == RefusalKind.IN_FLIGHT_UNIT
    assert "moves/1" in refusal.line
    assert state in refusal.line
    assert plan.units_blocking == ("moves/1",)


@pytest.mark.parametrize("state", ["merged", "failed"])
def test_a_merged_or_failed_unit_is_selected(tmp_path, state):
    source = source_with_a_moved_and_a_staying_change(tmp_path)
    write_units(source, new_unit("moves/1", state=state))

    plan = plan_split(source, "app")

    assert plan.units_moved == ("moves/1",)
    assert plan.refusals == ()
