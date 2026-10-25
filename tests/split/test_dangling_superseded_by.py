"""A replaced unit's `superseded_by` is checked for dangling ids as `depends_on` and `needs` are
(spec: a-replaced-unit-points-to-its-successor)."""

from agent_build_kit.split.copy import preflight
from agent_build_kit.split.select import plan_split
from tests.factories import new_unit
from tests.split_sources import source_installation, write_change, write_units


def installations(tmp_path):
    destination = source_installation(tmp_path / "destination")
    source = source_installation(tmp_path / "source")
    write_change(source, "moves", ["app", "app", "app"])
    write_change(source, "stays", ["lib"])
    return source, destination


def test_a_moved_unit_replaced_by_a_unit_that_stays_is_an_error_naming_unit_field_and_target(
    tmp_path,
):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="unplanned", superseded_by=("stays/1",)),
        new_unit("moves/2", state="merged"),
        new_unit("stays/1", repo="lib", state="merged"),
    )

    found = preflight(source, destination, plan_split(source, "app"))

    (error,) = found.errors
    assert all(word in error for word in ("moves/1", "superseded_by", "stays/1"))


def test_a_moved_unit_replaced_by_a_unit_that_moves_is_fine_and_a_staying_one_is_a_warning(
    tmp_path,
):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="unplanned", superseded_by=("moves/2",)),
        new_unit("moves/2", state="failed"),
        new_unit("stays/1", repo="lib", state="unplanned", superseded_by=("moves/2",)),
    )
    plan = plan_split(source, "app")

    kept = preflight(source, destination, plan)
    removing = preflight(source, destination, plan, remove=True)

    assert kept.errors == ()
    (warning,) = kept.warnings
    assert all(word in warning for word in ("stays/1", "superseded_by", "moves/2"))
    (error,) = removing.errors
    assert all(word in error for word in ("stays/1", "superseded_by", "moves/2"))
