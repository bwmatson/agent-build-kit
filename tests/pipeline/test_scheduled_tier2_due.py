"""Whether a repo's whole tier 2 suite is due is read from the dates in the names of its
scheduled changes, open or archived, with the repo's schedule in effect; a round writes one
change for a due repo with none open (spec: tier2-schedule)."""

from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.e2e_schedule import scheduled_name, scheduled_parts, write_due
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.untouched_failures import ensure_fix, preexisting_record
from tests.tier2_schedule_fakes import (
    TODAY,
    ago,
    archived,
    open_change,
    planning,
    scheduled_changes,
    store_of,
)
from tests.untouched_failure_fakes import failing


def round_of(inst, store, *, today=TODAY) -> tuple[list[str], list[str]]:
    """One round's write step: the names it wrote and the lines it said."""
    said: list[str] = []
    return write_due(inst, store, today=today, say=said.append), said


# --- the name -------------------------------------------------------------------


def test_the_name_is_the_prefix_the_repo_the_day_and_the_split() -> None:
    assert scheduled_name("app", TODAY) == "scheduled-e2e-app-2026-03-10-rest"


@pytest.mark.parametrize(
    ("name", "repo", "day"),
    [
        ("scheduled-tier2-app-2026-03-10", "app", (TODAY, "rest")),
        ("scheduled-tier2-app-web-2026-03-10", "app-web", (TODAY, "rest")),
        ("scheduled-tier2-app-web-2026-03-10", "app", None),
        ("scheduled-tier2-app-2026-03-10", "app-web", None),
        ("scheduled-tier2-app-extra", "app", None),
        ("scheduled-tier2-app-2026-13-40", "app", None),
        ("scheduled-tier2-app-2026-03-10-again", "app", None),
        ("fix-failing-app-2026-03-10", "app", None),
        ("scheduled-tier2-app", "app", None),
    ],
)
def test_the_date_is_read_from_the_name_of_exactly_that_repos_change(
    name: str, repo: str, day: object
) -> None:
    assert scheduled_parts(name, repo, ("rest",)) == day


# --- due ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schedule", "age", "due"),
    [
        ("weekly", 8, True),
        ("weekly", 7, True),
        ("weekly", 6, False),
        ("weekly", 3, False),
        ("daily", 1, True),
        ("daily", 0, False),
        ("monthly", 30, True),
        ("monthly", 29, False),
    ],
)
def test_a_repo_is_due_a_period_after_its_latest_change_whether_archived_or_open(
    tmp_path: Path, schedule: str, age: int, due: bool
) -> None:
    for kind in (archived, open_change):
        root = tmp_path / kind.__name__
        inst = planning(root, tier2_schedule=schedule)
        store = store_of(inst, "app")
        kind(inst, "app", ago(age))
        before = scheduled_changes(inst)

        written, _ = round_of(inst, store)

        # An open change is never joined by a second, so only the archived one can be due.
        expected = [scheduled_name("app", TODAY)] if due and kind is archived else []
        assert written == expected
        assert scheduled_changes(inst) == sorted(before + expected)


def test_weekly_is_the_default_without_any_setting(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    store = store_of(inst, "app")
    archived(inst, "app", ago(8))

    assert round_of(inst, store)[0] == [scheduled_name("app", TODAY)]


def test_the_latest_of_several_changes_decides(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    store = store_of(inst, "app")
    archived(inst, "app", ago(40))
    archived(inst, "app", ago(3))
    archived(inst, "app", ago(20))

    assert round_of(inst, store) == ([], [])
    assert scheduled_changes(inst) == []


def test_a_repo_with_no_earlier_change_is_due_at_once(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    store = store_of(inst, "app")

    written, said = round_of(inst, store)

    assert written == [scheduled_name("app", TODAY)]
    assert scheduled_changes(inst) == written
    assert f"wrote: {written[0]}" in said


def test_a_repo_with_no_tier_2_unit_gets_none(tmp_path: Path) -> None:
    inst = planning(tmp_path, {"app": None, "platform": None})
    store = store_of(inst, "app", platform="platform")

    written, _ = round_of(inst, store)

    assert written == [scheduled_name("app", TODAY)]
    assert scheduled_changes(inst) == [scheduled_name("app", TODAY)]


def test_an_empty_store_has_no_repo_to_schedule(tmp_path: Path) -> None:
    inst = planning(tmp_path)

    assert round_of(inst, store_of(inst)) == ([], [])


def test_a_repo_whose_name_begins_another_is_not_confused_with_it(tmp_path: Path) -> None:
    inst = planning(tmp_path, {"app": None, "app-web": None})
    store = store_of(inst, "app", "app-web")
    archived(inst, "app", ago(8))
    open_change(inst, "app-web", ago(1))
    archived(inst, "app-web", ago(30))

    written, _ = round_of(inst, store)

    # app-web's recent change does not keep app from being due, and app's does not make it
    # due or open for app-web, whose own one is still open.
    assert written == [scheduled_name("app", TODAY)]


def test_the_shorter_name_does_not_stand_for_the_longer_repo(tmp_path: Path) -> None:
    inst = planning(tmp_path, {"app": None, "app-web": None})
    store = store_of(inst, "app", "app-web")
    open_change(inst, "app", ago(1))
    archived(inst, "app", ago(2))
    archived(inst, "app-web", ago(20))

    written, _ = round_of(inst, store)

    assert written == [scheduled_name("app-web", TODAY)]


def test_two_repos_with_different_schedules_each_follow_their_own(tmp_path: Path) -> None:
    inst = planning(tmp_path, {"app": "off", "platform": "daily"}, tier2_schedule="weekly")
    store = store_of(inst, "app", "platform")
    archived(inst, "app", ago(30))
    archived(inst, "platform", ago(1))

    written, _ = round_of(inst, store)

    assert written == [scheduled_name("platform", TODAY)]
    tomorrow = TODAY + timedelta(days=1)
    (inst.changes_dir / scheduled_name("platform", TODAY)).rename(
        inst.changes_dir / "archive" / f"{TODAY}-{scheduled_name('platform', TODAY)}"
    )
    assert round_of(inst, store, today=TODAY)[0] == [], "daily: not due the day it was written"
    assert round_of(inst, store, today=tomorrow)[0] == [scheduled_name("platform", tomorrow)]


def test_the_repos_value_wins_over_limits_in_both_directions(tmp_path: Path) -> None:
    inst = planning(tmp_path, {"app": "monthly", "platform": "daily"}, tier2_schedule="weekly")
    store = store_of(inst, "app", "platform")
    archived(inst, "app", ago(8))
    archived(inst, "platform", ago(1))

    assert round_of(inst, store)[0] == [scheduled_name("platform", TODAY)]


@pytest.mark.parametrize("where", ["limits", "repo"])
def test_off_writes_nothing_for_its_repo_across_any_number_of_rounds(
    tmp_path: Path, where: str
) -> None:
    inst = (
        planning(tmp_path, tier2_schedule="off")
        if where == "limits"
        else planning(tmp_path, {"app": "off"})
    )
    store = store_of(inst, "app")

    for weeks in range(8):
        assert round_of(inst, store, today=TODAY + timedelta(weeks=weeks)) == ([], [])

    assert scheduled_changes(inst) == []


def test_off_still_reads_the_record_of_pre_existing_failures_and_writes_their_fix(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path, {"app": "off"})
    store = store_of(inst, "app")
    entry = failing(unit="app-work/1")
    preexisting_record(inst).append(entry)

    assert round_of(inst, store) == ([], [])
    fix = ensure_fix(inst, entry, store.get("app-work/1"), say=lambda line: None)

    assert fix.startswith("fix-failing-")
    assert [e.test for e in preexisting_record(inst).entries()] == [entry.test]
    assert scheduled_changes(inst) == []


# --- one at a time --------------------------------------------------------------


@pytest.mark.parametrize(
    "state", [UnitState.RUNNING, UnitState.FAILED, UnitState.HELD, UnitState.PLANNED]
)
def test_no_second_change_is_written_while_one_of_the_repo_is_open(
    tmp_path: Path, state: UnitState
) -> None:
    inst = planning(tmp_path)
    store = store_of(inst, "app")
    existing = open_change(inst, "app", ago(60))
    store.set_state("app-work/1", state)

    written, said = round_of(inst, store)

    assert written == []
    assert scheduled_changes(inst) == [existing]
    assert said == [f"exists: {existing}"]


def test_another_repos_open_change_does_not_keep_this_repo_from_being_written(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path, {"app": None, "platform": None})
    store = store_of(inst, "app", "platform")
    open_change(inst, "platform", ago(60))

    assert round_of(inst, store)[0] == [scheduled_name("app", TODAY)]


def test_five_missed_weeks_write_one_change_and_a_second_round_writes_none(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    store = store_of(inst, "app")
    archived(inst, "app", ago(35))

    first, _ = round_of(inst, store)
    second, said = round_of(inst, store)

    assert first == [scheduled_name("app", TODAY)]
    assert second == []
    assert scheduled_changes(inst) == first
    assert said == [f"exists: {first[0]}"]


def test_the_date_is_read_from_the_name_and_nothing_is_stored(tmp_path: Path) -> None:
    inst = planning(tmp_path)
    store = store_of(inst, "app")
    before = {p.name for p in inst.state_dir.iterdir()}

    [name] = round_of(inst, store)[0]

    assert {p.name for p in inst.state_dir.iterdir()} <= before | {"scheduled-e2e.lock"}
    # Archived on a later day than it was written: the date in the name is the one that counts.
    (inst.changes_dir / "archive").mkdir()
    (inst.changes_dir / name).rename(inst.changes_dir / "archive" / f"2026-04-20-{name}")
    assert round_of(inst, store, today=TODAY + timedelta(days=6))[0] == []
    seventh = TODAY + timedelta(days=7)
    assert round_of(inst, store, today=seventh)[0] == [scheduled_name("app", seventh)]


def test_two_writers_at_once_write_one_change_and_the_second_says_it_exists(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    store = store_of(inst, "app")
    meeting = threading.Barrier(2)
    results: list[tuple[list[str], list[str]]] = []

    def write() -> None:
        meeting.wait()
        results.append(round_of(inst, store))

    writers = [threading.Thread(target=write) for _ in range(2)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=30)

    name = scheduled_name("app", TODAY)
    assert scheduled_changes(inst) == [name]
    [(none, existing), (one, wrote)] = sorted(results, key=lambda result: len(result[0]))
    assert none == [] and existing == [f"exists: {name}"]
    assert one == [name] and wrote[-1] == f"wrote: {name}"
