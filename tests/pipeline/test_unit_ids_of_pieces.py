"""A piece made by a split has an id that extends its parent's, and no reader of an id breaks on it
(spec: unit-superseding)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.pipeline.run_log import RUNS_KEPT, RunLog, run_log_dir, run_log_name
from agent_build_kit.pipeline.transcript import (
    Transcript,
    TranscriptEvent,
    read_transcripts,
    transcript_dir,
    unit_transcript_files,
)
from agent_build_kit.pipeline.units import branch_name, earlier_units, unit_number
from tests.factories import stored_unit, unit

START = datetime(2026, 9, 23, 22, 44, 5, tzinfo=UTC)
PARENT = "app/3"
PIECE = "app/3-s1"


def test_the_number_of_a_piece_is_the_integer_after_the_change() -> None:
    assert unit_number(unit("app/3-s2-s1", change="app")) == 3
    assert unit_number(unit("app/3-s1", change="app")) == 3
    assert unit_number(unit("app/12", change="app")) == 12, "an ordinary id is as before"


def test_an_acceptance_unit_follows_a_piece_of_an_earlier_unit() -> None:
    piece = stored_unit(PIECE, change="app", groups=(3,))
    acceptance = stored_unit("app/5", change="app", groups=(5,), flag="acceptance")
    later = stored_unit("app/6", change="app", groups=(6,))

    assert [u.id for u in earlier_units(acceptance, [piece, acceptance, later])] == [PIECE]


def test_a_piece_is_not_among_the_units_before_an_earlier_numbered_unit() -> None:
    acceptance = stored_unit("app/2", change="app", groups=(2,), flag="acceptance")
    piece = stored_unit(PIECE, change="app", groups=(3,))

    assert earlier_units(acceptance, [acceptance, piece]) == []


def test_the_branch_and_run_log_names_of_a_piece_are_made_from_its_id() -> None:
    assert branch_name(unit(PIECE, change="app")) == "spec/app/3-s1"
    assert branch_name(unit("app/3", change="app")) == "spec/app/3"
    parent = run_log_name(unit(PARENT, change="app"), START, "implement")
    piece = run_log_name(unit(PIECE, change="app"), START, "implement")

    assert parent == "app-03-20260923-224405-implement.log"
    assert piece == "app-03-s1-20260923-224405-implement.log"


def start_runs(directory: Path, uid: str, count: int) -> None:
    for second in range(count):
        RunLog(
            directory,
            unit(uid, change="app"),
            step="implement",
            model="m",
            base="main",
            started=START.replace(second=second),
        )


def test_a_pieces_run_logs_are_pruned_by_its_own_id_and_not_its_parents(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    start_runs(directory, PARENT, 1)
    start_runs(directory, PIECE, RUNS_KEPT + 1)

    names = sorted(path.name for path in directory.iterdir())

    assert sum(name.startswith("app-03-s1-") for name in names) == RUNS_KEPT
    assert [name for name in names if not name.startswith("app-03-s1-")] == [
        run_log_name(unit(PARENT, change="app"), START.replace(second=0), "implement")
    ]


def test_a_parents_run_logs_are_pruned_without_touching_its_pieces(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    start_runs(directory, PIECE, 1)
    start_runs(directory, PARENT, RUNS_KEPT + 1)

    names = sorted(path.name for path in directory.iterdir())

    assert [name for name in names if name.startswith("app-03-s1-")] == [
        run_log_name(unit(PIECE, change="app"), START.replace(second=0), "implement")
    ]
    assert sum(not name.startswith("app-03-s1-") for name in names) == RUNS_KEPT


def record(directory: Path, uid: str, text: str) -> None:
    Transcript(
        directory,
        unit(uid, change="app"),
        node="implement",
        round=1,
        source="build",  # pyrefly: ignore
        started=START,
        result_limit=1000,
        runs_kept=3,
    ).record(TranscriptEvent(kind="text", text=text, session="s"))  # pyrefly: ignore


def test_transcripts_of_a_unit_and_its_piece_are_found_each_by_its_own_id(tmp_path: Path) -> None:
    directory = transcript_dir(tmp_path)
    record(directory, PARENT, "parent said")
    record(directory, PIECE, "piece said")

    assert [event.text for event in read_transcripts(directory, PARENT)] == ["parent said"]
    assert [event.text for event in read_transcripts(directory, PIECE)] == ["piece said"]
    assert len(unit_transcript_files(directory, PARENT)) == 1
    assert len(unit_transcript_files(directory, PIECE)) == 1
