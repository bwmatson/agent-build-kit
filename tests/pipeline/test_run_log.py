"""A file per unit run, named for the unit.

The journal keys a run by time; someone diagnosing a unit asks about the unit.
So the name leads with the unit, the header says what the run was, and the
file carries that unit's lines and no one else's.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.run_log import (
    RUNS_KEPT,
    RunLog,
    remove_change_logs,
    run_log_dir,
    run_log_name,
)
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import stored_unit, unit
from tests.pipeline.test_archive import FakeRunner

START = datetime(2026, 9, 23, 22, 44, 5, tzinfo=UTC)


def start_run(
    directory: Path, uid: str = "add-marker/1", *, at: datetime = START, step: str = "implement"
) -> RunLog:
    change = uid.split("/")[0]
    return RunLog(
        directory,
        unit(uid, change=change),
        step=step,
        model="model-x",
        base="main",
        started=at,
    )


def test_the_name_is_change_padded_number_start_time_then_step() -> None:
    name = run_log_name(unit("add-marker/1"), START, "implement")

    assert name == "add-marker-01-20260923-224405-implement.log"


def test_units_of_one_change_sort_in_numeric_order() -> None:
    names = [run_log_name(unit(f"add-marker/{n}"), START, "implement") for n in (10, 2, 1)]

    assert sorted(names) == [
        run_log_name(unit(f"add-marker/{n}"), START, "implement") for n in (1, 2, 10)
    ]


def test_runs_of_one_unit_sort_by_time_and_group_together() -> None:
    later = START + timedelta(hours=1)
    names = [
        run_log_name(unit("add-marker/2"), later, "review"),
        run_log_name(unit("add-marker/1"), START, "implement"),
        run_log_name(unit("add-marker/2"), START, "implement"),
        run_log_name(unit("add-marker/1"), later, "rework"),
    ]

    assert sorted(names) == [
        "add-marker-01-20260923-224405-implement.log",
        "add-marker-01-20260923-234405-rework.log",
        "add-marker-02-20260923-224405-implement.log",
        "add-marker-02-20260923-234405-review.log",
    ]


def test_a_run_writes_a_file_named_for_it_in_the_directory(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)

    log = start_run(directory)
    log.close("open")

    assert log.name == "add-marker-01-20260923-224405-implement.log"
    assert [path.name for path in directory.iterdir()] == [log.name]


def test_the_directory_is_its_own_under_the_state_directory(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)

    assert directory.parent == tmp_path
    assert directory != tmp_path


def test_the_file_opens_with_what_the_run_was(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    log = start_run(directory, "add-marker/3", step="rework")
    log.emit("step: rework from feedback")
    log.close("open")

    text = (directory / log.name).read_text()
    header = text.split("step: rework from feedback")[0]

    for fact in ("add-marker/3", "add-marker", "rework", "model-x", "main", "2026-09-23"):
        assert fact in header, f"{fact!r} is stated before the transcript"


def test_the_file_carries_the_lines_emitted_in_order(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    log = start_run(directory)
    log.emit("step: write the tests")
    log.emit("tier 1 passed")
    log.close("open")

    text = (directory / log.name).read_text()

    assert text.index("step: write the tests") < text.index("tier 1 passed")


def test_the_file_closes_with_the_outcome(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    log = start_run(directory)
    log.emit("step: implement")
    log.close("failed: tier 1 did not pass")

    lines = (directory / log.name).read_text().rstrip().splitlines()

    assert "failed: tier 1 did not pass" in lines[-1]


def test_another_units_lines_are_not_in_the_file(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    mine = start_run(directory, "add-marker/1")
    theirs = start_run(directory, "add-marker/2")

    mine.emit("mine: only")
    theirs.emit("theirs: elsewhere")
    mine.close("open")
    theirs.close("open")

    assert "theirs: elsewhere" not in (directory / mine.name).read_text()
    assert "mine: only" not in (directory / theirs.name).read_text()


def test_only_the_bounded_number_of_runs_per_unit_is_kept(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    runs = RUNS_KEPT + 2
    newest = START + timedelta(hours=runs - 1)
    for hour in range(runs):
        start_run(directory, at=START + timedelta(hours=hour)).close("open")

    kept = sorted(path.name for path in directory.glob("add-marker-01-*"))

    assert len(kept) == RUNS_KEPT
    assert kept[-1] == run_log_name(unit("add-marker/1"), newest, "implement"), (
        "the most recent runs are the ones kept"
    )


def test_pruning_one_unit_leaves_the_others(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    other = start_run(directory, "add-marker/2")
    other.close("open")

    for hour in range(RUNS_KEPT + 2):
        start_run(directory, at=START + timedelta(hours=hour)).close("open")

    assert (directory / other.name).exists()


def test_removing_a_changes_logs_leaves_other_changes(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    start_run(directory, "other/1").close("open")
    start_run(directory, "add-marker/1").close("open")
    start_run(directory, "add-marker/2").close("open")

    remove_change_logs(directory, "add-marker")

    assert [path.name for path in directory.iterdir()] == ["other-01-20260923-224405-implement.log"]


def test_removing_the_logs_of_a_change_that_never_ran_is_harmless(tmp_path: Path) -> None:
    remove_change_logs(run_log_dir(tmp_path), "add-marker")


def test_a_change_whose_name_begins_with_another_keeps_its_logs(tmp_path: Path) -> None:
    """`add-marker-v2-01-…` also begins with `add-marker-` if names are matched loosely."""
    directory = run_log_dir(tmp_path)
    start_run(directory, "add-marker-v2/1").close("open")
    start_run(directory, "add-marker/1").close("open")

    remove_change_logs(directory, "add-marker")

    assert [path.name for path in directory.iterdir()] == [
        "add-marker-v2-01-20260923-224405-implement.log"
    ]


def test_archiving_a_change_removes_its_units_logs(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    start_run(directory, "add-marker/1").close("open")
    start_run(directory, "add-marker/2").close("open")
    units = [
        stored_unit("add-marker/1", state="merged"),
        stored_unit("add-marker/2", state="merged"),
    ]

    archived = archive_ready_changes(
        units, planning_repo=tmp_path, run=FakeRunner(), run_logs=directory
    )

    assert archived == ["add-marker"]
    assert list(directory.iterdir()) == []


def test_a_change_not_archived_keeps_its_logs(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    start_run(directory, "add-marker/1").close("open")
    units = [
        stored_unit("add-marker/1", state="merged"),
        stored_unit("add-marker/2", state="in_review"),
    ]

    archive_ready_changes(units, planning_repo=tmp_path, run=FakeRunner(), run_logs=directory)

    assert len(list(directory.iterdir())) == 1


def test_the_store_records_a_units_most_recent_run_log(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    name = "add-marker-01-20260923-224405-implement.log"

    store.set_run_log("add-marker/1", name)

    assert store.get("add-marker/1").run_log == name


def test_a_replan_keeps_the_units_run_log(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    name = "add-marker-01-20260923-224405-implement.log"
    store.set_run_log("add-marker/1", name)

    store.upsert([unit()])

    assert store.get("add-marker/1").run_log == name


def test_a_log_that_cannot_be_written_is_reported_once_and_never_raises(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    directory.write_text("a file, not a directory")
    reported: list[str] = []

    log = RunLog(
        directory,
        unit(),
        step="implement",
        model="m",
        base="main",
        started=START,
        report=reported.append,
    )
    log.emit("a line")
    log.close("open")

    assert len(reported) == 1
    assert "not written" in reported[0]


def test_a_log_that_fails_midway_stops_writing_and_reports_once(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    reported: list[str] = []
    log = RunLog(
        directory,
        unit(),
        step="implement",
        model="m",
        base="main",
        started=START,
        report=reported.append,
    )
    (directory / log.name).unlink()
    (directory / log.name).mkdir()

    log.emit("a line")
    log.close("open")

    assert len(reported) == 1
