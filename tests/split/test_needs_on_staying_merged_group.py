"""A moved `Needs:` on a staying change whose group is merged history is a note, and the copied
tasks file is left as it is."""

from datetime import UTC, datetime

import pytest

from agent_build_kit.cli.pipeline import awaiting_planning, declared_needs, link_needs
from agent_build_kit.pipeline import loaded_code
from agent_build_kit.pipeline.cycles import needs_cycle
from agent_build_kit.pipeline.loaded_code import LoadedCode, TickRecord
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import waiting_on
from agent_build_kit.pipeline.work_graph import check_tags
from agent_build_kit.split.copy import carry_out, preflight
from agent_build_kit.split.select import plan_split
from tests.factories import new_unit
from tests.split_sources import source_installation, write_change, write_units

TICK = 5


@pytest.fixture(autouse=True)
def tick():
    loaded_code.running_tick(TickRecord(number=TICK, started_at=datetime(2026, 1, 1, tzinfo=UTC)))
    yield
    loaded_code.running_tick(None)


def installations(tmp_path, *, needs="m group 4"):
    """A moved change `g` whose group 1 carries `Needs: <needs>` and whose group 2 carries
    `Needs: m group 3`, which is merged history; `m` is a mixed change kept in the source."""
    destination = source_installation(tmp_path / "destination")
    source = source_installation(tmp_path / "source")
    write_change(source, "m", ["app", "lib", "app", "app"])
    write_change(source, "lib-change", ["lib"])
    tasks = write_change(source, "g", ["app", "app"]) / "tasks.md"
    tasks.write_text(
        "# Tasks\n\nAcceptance: none — fixture\n\n"
        f"## 1. [app] [unit-test] Group 1\n\nNeeds: {needs}\n\n- [ ] 1.1 Test: it\n\n"
        "## 2. [app] [unit-test] Group 2\n\nNeeds: m group 3\n\n- [ ] 2.1 Test: it\n"
    )
    return source, destination


def merged(uid, **overrides):
    return new_unit(uid, repo="app", state="merged", **overrides)


def check(source, destination):
    return preflight(source, destination, plan_split(source, "app", allow_mixed="source"))


def test_a_needs_on_a_merged_loaded_group_is_a_warning_naming_the_change_and_group(tmp_path):
    source, destination = installations(tmp_path)
    write_units(source, new_unit("g/1"), merged("m/3"), merged("m/4"))

    found = check(source, destination)

    assert found.errors == ()
    assert len(found.warnings) == 2
    (warning,) = (w for w in found.warnings if "group 1" in w)
    assert all(word in warning for word in ("g", "m group 4", "m"))


@pytest.mark.parametrize(
    "target",
    [
        pytest.param(new_unit("m/4", repo="app", state="in_review"), id="in_review"),
        pytest.param(None, id="no unit builds the group"),
        pytest.param(merged("m/4", groups=(1,)), id="unit builds another group"),
    ],
)
def test_a_needs_on_a_group_that_is_not_merged_history_is_an_error(tmp_path, target):
    source, destination = installations(tmp_path)
    write_units(source, new_unit("g/1"), merged("m/3"), *([target] if target else []))

    found = check(source, destination)

    (error,) = found.errors
    assert all(word in error for word in ("change g", "group 1", "m group 4"))
    (warning,) = found.warnings
    assert "group 2" in warning


def test_a_needs_on_a_merged_group_that_is_not_loaded_says_to_run_a_tick(tmp_path):
    source, destination = installations(tmp_path)
    write_units(source, new_unit("g/1"), merged("m/3"), merged("m/4", merged_tick=TICK))

    found = check(source, destination)

    (error,) = found.errors
    assert all(word in error for word in ("group 1", "m group 4", "tick"))
    (warning,) = found.warnings
    assert "group 2" in warning


def test_a_group_built_by_a_merged_unit_and_an_unmerged_one_is_an_error(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("g/1"),
        merged("m/3"),
        merged("m/4", groups=(4,)),
        new_unit("m/5", repo="app", state="in_review", groups=(4,)),
    )

    found = check(source, destination)

    (error,) = found.errors
    assert all(word in error for word in ("group 1", "m group 4"))
    (warning,) = found.warnings
    assert "group 2" in warning


def test_a_needs_on_a_merged_group_of_another_repos_change_is_the_same_warning(tmp_path):
    source, destination = installations(tmp_path, needs="lib-change group 1")
    write_units(
        source,
        new_unit("g/1"),
        merged("m/3"),
        new_unit("lib-change/1", repo="lib", state="merged"),
    )

    found = check(source, destination)

    assert found.errors == ()
    (warning,) = (w for w in found.warnings if "group 1" in w)
    assert "lib-change group 1" in warning


def test_the_copied_tasks_file_equals_the_sources_after_a_second_run_too(tmp_path):
    source, destination = installations(tmp_path)
    write_units(source, new_unit("g/1"), merged("m/3"), merged("m/4"))
    plan = plan_split(source, "app", allow_mixed="source")
    original = (source.changes_dir / "g" / "tasks.md").read_bytes()

    carry_out(source, destination, plan)
    carry_out(source, destination, plan)

    assert (destination.changes_dir / "g" / "tasks.md").read_bytes() == original
    assert (source.changes_dir / "g" / "tasks.md").read_bytes() == original


def test_the_destination_holding_the_copied_change_and_no_m_treats_the_line_as_inert(tmp_path):
    source, destination = installations(tmp_path)
    write_units(
        source,
        new_unit("g/1", depends_on=("m/4",), needs=("m/4",)),
        merged("m/3"),
        merged("m/4"),
    )
    carry_out(source, destination, plan_split(source, "app", allow_mixed="source"))
    store = UnitStore(destination.state_dir / "units.json")
    units = store.all()
    heard: list[tuple[str, int]] = []

    _, problems = check_tags("g", destination.changes_dir, repos=("app", "lib"))
    declared = declared_needs(
        destination, units, missing=lambda change, group, need: heard.append((change, group))
    )
    cycle = needs_cycle(destination.tasks_files())
    cycles = link_needs(destination, store=store)

    (moved,) = units
    assert problems == []
    assert [need for found in declared.values() for need in found] == []
    assert heard == [("g", 1), ("g", 2)]
    assert awaiting_planning(destination, moved, units) == []
    assert cycle == ()
    assert waiting_on(moved, units, LoadedCode(number=TICK)) == []
    assert cycles == []
    assert store.get("g/1").depends_on == ()
    assert store.get("g/1").needs == ()
