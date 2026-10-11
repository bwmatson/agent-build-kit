"""The decision log and old unit logs are bounded (spec: unit-timeline-is-recorded, run-logs,
The decision log and old unit logs are bounded).

A unit's log is a diagnostic copy of what its summary line in the usage ledger already says,
so it goes by age only once that line is written.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.config import WorkspaceConfig, load
from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.run_log import remove_old_logs, run_log_dir
from agent_build_kit.pipeline.wait_log import trim_decision_log
from tests.factories import stored_unit
from tests.pipeline.test_archive import FakeRunner
from tests.pipeline.test_run_log import START, start_run

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
DAYS = 30


def decisions(path: Path, count: int) -> list[str]:
    """`count` lines of the decision log, numbered in the order written."""
    lines = [
        json.dumps(
            {"at": NOW.isoformat(), "unit": "add-marker/2", "reason": "blocked", "tick": f"t{n}"}
        )
        for n in range(count)
    ]
    path.write_text("".join(f"{line}\n" for line in lines))
    return lines


def aged(path: Path, *, days: float) -> Path:
    stamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def log_of(directory: Path, uid: str, *, days: float) -> Path:
    """A closed run log of the unit, last written `days` before `NOW`."""
    start_run(directory, uid, at=START).close("open")
    (path,) = [p for p in directory.iterdir() if p.name.startswith(uid.replace("/", "-0"))]
    return aged(path, days=days)


def ledger_with_summaries(path: Path, *units: str) -> Path:
    path.write_text(
        "".join(
            json.dumps({"kind": "summary", "unit": u, "change": u.split("/")[0]}) + "\n"
            for u in units
        )
    )
    return path


# --- the decision log is bounded by size ------------------------------------------------


def test_a_decision_log_over_its_limit_keeps_its_newest_lines(tmp_path: Path) -> None:
    path = tmp_path / "decisions.jsonl"
    lines = decisions(path, 400)
    limit_mb = (sum(len(x) + 1 for x in lines) // 2) / (1024 * 1024)

    trim_decision_log(path, limit_mb=limit_mb)

    kept = path.read_text().splitlines()
    assert 0 < len(kept) < 400
    assert kept == lines[-len(kept) :], "the newest lines, in order, each whole"
    assert path.stat().st_size <= limit_mb * 1024 * 1024


def test_a_trim_leaves_room_so_one_more_line_does_not_trim_again(tmp_path: Path) -> None:
    path = tmp_path / "decisions.jsonl"
    lines = decisions(path, 400)
    limit_mb = (sum(len(x) + 1 for x in lines) // 2) / (1024 * 1024)
    trim_decision_log(path, limit_mb=limit_mb)
    with path.open("a") as file:
        file.write(lines[0] + "\n")
    before = path.stat().st_ino, path.read_text()

    trim_decision_log(path, limit_mb=limit_mb)

    assert (path.stat().st_ino, path.read_text()) == before, "not rewritten for one more line"


def test_a_trim_that_cannot_write_leaves_the_log_and_no_scratch_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "decisions.jsonl"
    decisions(path, 400)
    before = path.read_text()

    def full_disk(self: Path, data: bytes) -> int:
        self.touch()
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "write_bytes", full_disk)
    trim_decision_log(path, limit_mb=0.001)

    assert path.read_text() == before
    assert [p.name for p in tmp_path.iterdir()] == ["decisions.jsonl"]


def test_a_decision_log_within_its_limit_is_left_as_it_is(tmp_path: Path) -> None:
    path = tmp_path / "decisions.jsonl"
    decisions(path, 5)
    before = path.read_text()

    trim_decision_log(path, limit_mb=50)

    assert path.read_text() == before


def test_a_decision_log_that_is_not_there_is_not_made(tmp_path: Path) -> None:
    trim_decision_log(tmp_path / "decisions.jsonl", limit_mb=50)

    assert not (tmp_path / "decisions.jsonl").exists()


# --- an old unit log goes once its summary is written -----------------------------------


def test_an_old_log_with_a_summary_is_removed(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    old = log_of(directory, "add-marker/1", days=DAYS + 1)
    ledger = ledger_with_summaries(tmp_path / "usage-ledger.jsonl", "add-marker/1")

    remove_old_logs(directory, ledger, days=DAYS, now=NOW)

    assert not old.exists()


def test_an_old_log_without_a_summary_is_kept(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    old = log_of(directory, "add-marker/1", days=DAYS + 1)
    ledger = ledger_with_summaries(tmp_path / "usage-ledger.jsonl", "add-marker/2")

    remove_old_logs(directory, ledger, days=DAYS, now=NOW)

    assert old.exists()


def test_an_old_log_is_kept_when_there_is_no_ledger(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    old = log_of(directory, "add-marker/1", days=DAYS + 1)

    remove_old_logs(directory, tmp_path / "usage-ledger.jsonl", days=DAYS, now=NOW)

    assert old.exists()


def test_the_ledger_is_not_read_while_no_log_is_old_enough(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    recent = log_of(directory, "add-marker/1", days=DAYS - 1)
    ledger = tmp_path / "usage-ledger.jsonl"
    ledger.mkdir()  # reading it as a file would raise

    remove_old_logs(directory, ledger, days=DAYS, now=NOW)

    assert recent.exists()


def test_a_log_within_the_age_is_kept_with_its_summary(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    recent = log_of(directory, "add-marker/1", days=DAYS - 1)
    ledger = ledger_with_summaries(tmp_path / "usage-ledger.jsonl", "add-marker/1")

    remove_old_logs(directory, ledger, days=DAYS, now=NOW)

    assert recent.exists()


def test_only_the_old_logs_of_a_summarised_unit_go(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    old = log_of(directory, "add-marker/1", days=DAYS + 5)
    other = log_of(directory, "add-marker/2", days=DAYS + 5)
    ledger = ledger_with_summaries(tmp_path / "usage-ledger.jsonl", "add-marker/1")

    remove_old_logs(directory, ledger, days=DAYS, now=NOW)

    assert not old.exists()
    assert other.exists(), "the unit with no summary keeps its log"


def test_a_directory_that_is_not_there_is_not_an_error(tmp_path: Path) -> None:
    remove_old_logs(
        run_log_dir(tmp_path),
        ledger_with_summaries(tmp_path / "usage-ledger.jsonl", "add-marker/1"),
        days=DAYS,
        now=NOW,
    )


def test_archiving_still_removes_the_logs_of_a_change_old_or_not(tmp_path: Path) -> None:
    (tmp_path / "openspec" / "changes" / "add-marker").mkdir(parents=True)
    directory = run_log_dir(tmp_path)
    log_of(directory, "add-marker/1", days=DAYS + 1)
    log_of(directory, "add-marker/2", days=1)
    units = [
        stored_unit("add-marker/1", state="merged"),
        stored_unit("add-marker/2", state="merged"),
    ]

    archived = archive_ready_changes(
        units, planning_repo=tmp_path, run=FakeRunner(), run_logs=directory
    )

    assert archived == ["add-marker"]
    assert list(directory.iterdir()) == []


# --- the settings -----------------------------------------------------------------------


def test_the_retention_defaults_are_fifty_megabytes_and_thirty_days() -> None:
    retention = WorkspaceConfig().retention  # pyrefly: ignore

    assert retention.decision_log_mb == 50
    assert retention.unit_log_days == 30


def test_abk_yaml_sets_the_retention(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text("retention:\n  decision_log_mb: 5\n  unit_log_days: 7\n")

    loaded = load(path)

    assert loaded.retention.decision_log_mb == 5  # pyrefly: ignore
    assert loaded.retention.unit_log_days == 7  # pyrefly: ignore
