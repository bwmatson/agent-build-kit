"""A staying edge into a moved merged unit is a warning, even under `--remove`."""

from agent_build_kit.pipeline.loaded_code import LoadedCode
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import waiting_on
from agent_build_kit.split.copy import preflight
from agent_build_kit.split.remove import remove
from agent_build_kit.split.select import plan_split
from tests.factories import new_unit
from tests.split_sources import source_installation, write_change, write_units


def installations(tmp_path):
    destination = source_installation(tmp_path / "destination")
    source = source_installation(tmp_path / "source")
    write_change(source, "moves", ["app", "app"])
    write_change(source, "stays", ["lib"])
    return source, destination


def test_a_staying_edge_into_a_moved_merged_unit_is_a_warning_with_and_without_remove(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged"),
        new_unit("stays/1", repo="lib", depends_on=("moves/1",)),
    )
    plan = plan_split(source, "app")

    kept = preflight(source, destination, plan)
    removing = preflight(source, destination, plan, remove=True)

    for found in (kept, removing):
        assert found.errors == ()
        (warning,) = found.warnings
        assert all(word in warning for word in ("stays/1", "depends_on", "moves/1"))


def test_only_an_edge_into_a_moved_unit_that_is_not_merged_is_an_error_under_remove(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged"),
        new_unit("moves/2", state="failed"),
        new_unit("stays/1", repo="lib", depends_on=("moves/1",)),
        new_unit("stays/2", repo="lib", depends_on=("moves/2",)),
    )
    plan = plan_split(source, "app")

    kept = preflight(source, destination, plan)
    removing = preflight(source, destination, plan, remove=True)

    assert kept.errors == ()
    assert len(kept.warnings) == 2
    (error,) = removing.errors
    assert all(word in error for word in ("stays/2", "depends_on", "moves/2"))
    (warning,) = removing.warnings
    assert all(word in warning for word in ("stays/1", "depends_on", "moves/1"))


def test_after_remove_the_staying_record_is_unchanged_and_waits_on_nothing(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("moves/1", state="merged"),
        new_unit("stays/1", repo="lib", depends_on=("moves/1",)),
    )
    plan = plan_split(source, "app")
    store = UnitStore(source.state_dir / "units.json")
    before = store.get("stays/1").model_dump_json()

    assert preflight(source, destination, plan, remove=True).errors == ()
    remove(source, plan)

    remaining = store.all()
    (staying,) = remaining
    assert staying.model_dump_json() == before
    assert waiting_on(staying, remaining, LoadedCode(number=1)) == []
