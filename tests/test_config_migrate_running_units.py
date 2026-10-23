"""The migration names the running units before it asks
(spec: config-migration, "The migration names the running units before it asks")."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config_migrate_write import running_units_notice
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, PLANNED, RUNNING, UnitState
from tests.factories import stored_unit

TAIL = "A write to abk.yaml or abk.local.yaml fails a build or track run in progress, so run this"
BETWEEN = "between ticks or when"


def store_in(directory: Path, states: dict[str, UnitState]) -> UnitStore:
    """A unit store at `directory/units.json` holding a unit per id, each in its state."""
    store = UnitStore(directory / "units.json")
    store.upsert([stored_unit(uid, change=uid.split("/")[0]) for uid in states])
    for uid, state in states.items():
        if state == HELD:
            store.set_state(uid, HELD, held_by=HeldBy.SIZE, cause=Cause.TOO_BIG_FOR_TIER)
        elif state != PLANNED:
            store.set_state(uid, state)
    return store


def planning(tmp_path: Path, text: str = "version: 1\n") -> Path:
    base = tmp_path / "abk.yaml"
    base.write_text(text)
    return base


def test_one_running_unit_gives_the_exact_notice(tmp_path: Path) -> None:
    store_in(tmp_path / "runs", {"a-change/2": RUNNING})

    assert running_units_notice(planning(tmp_path)) == (
        f"abk: 1 unit is running (a-change/2). {TAIL} {BETWEEN} it has finished."
    )


def test_three_running_units_are_all_named(tmp_path: Path) -> None:
    ids = ["a-change/1", "a-change/2", "a-change/3"]
    store_in(tmp_path / "runs", dict.fromkeys(ids, RUNNING))

    assert running_units_notice(planning(tmp_path)) == (
        f"abk: 3 units are running ({', '.join(ids)}). {TAIL} {BETWEEN} they have finished."
    )


def test_seven_running_units_name_five_and_count_the_rest(tmp_path: Path) -> None:
    ids = [f"a-change/{n}" for n in range(1, 8)]
    store_in(tmp_path / "runs", dict.fromkeys(ids, RUNNING))

    notice = running_units_notice(planning(tmp_path))

    assert notice is not None
    assert notice.startswith(f"abk: 7 units are running ({', '.join(ids[:5])}")
    assert "and 2 more)" in notice
    assert ids[5] not in notice
    assert notice.endswith(f"{TAIL} {BETWEEN} they have finished.")


def test_units_that_are_not_running_give_no_notice(tmp_path: Path) -> None:
    store_in(
        tmp_path / "runs",
        {
            "a-change/1": IN_REVIEW,
            "a-change/2": FAILED,
            "a-change/3": HELD,
            "a-change/4": PLANNED,
        },
    )

    assert running_units_notice(planning(tmp_path)) is None


def test_a_missing_store_gives_no_notice(tmp_path: Path) -> None:
    assert running_units_notice(planning(tmp_path)) is None


@pytest.mark.parametrize("kind", ["corrupt", "unreadable"])
def test_a_corrupt_or_unreadable_store_gives_no_notice_and_no_error(
    tmp_path: Path, kind: str
) -> None:
    (tmp_path / "runs").mkdir()
    store = tmp_path / "runs" / "units.json"
    if kind == "corrupt":
        store.write_text("{not json")
    else:
        store.mkdir()

    assert running_units_notice(planning(tmp_path)) is None


def test_the_state_directory_comes_from_the_raw_documents_without_loading_the_configuration(
    tmp_path: Path,
) -> None:
    store_in(tmp_path / "from-local", {"a-change/1": RUNNING})
    store_in(tmp_path / "from-base", {"other/1": RUNNING, "other/2": RUNNING})
    base = planning(
        tmp_path, "bogus_key_the_schema_forbids: 1\nplanning:\n  state_dir: from-base\n"
    )
    (tmp_path / "abk.local.yaml").write_text("planning:\n  state_dir: from-local\n")

    notice = running_units_notice(base)

    assert notice is not None
    assert notice.startswith("abk: 1 unit is running (a-change/1)")


def test_an_absolute_state_directory_is_read(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    store_in(elsewhere, {"a-change/1": RUNNING})
    directory = tmp_path / "plan"
    directory.mkdir()
    base = planning(directory, f"planning:\n  state_dir: {elsewhere}\n")

    notice = running_units_notice(base)

    assert notice is not None
    assert "(a-change/1)" in notice


def test_a_state_directory_under_the_home_directory_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    store_in(home / "state", {"a-change/1": RUNNING})
    directory = tmp_path / "plan"
    directory.mkdir()
    base = planning(directory, "planning:\n  state_dir: " + "~" + "/state\n")

    notice = running_units_notice(base)

    assert notice is not None
    assert "(a-change/1)" in notice
