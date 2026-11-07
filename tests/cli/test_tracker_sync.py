"""`abk tracker sync` runs the push then the pull once, with a dry run (spec: tracker-rollout)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.tracker_cmd_support import APP, Mirror
from tests.trackers.board_support import CHANGE


def test_a_dry_run_lists_the_creates_and_makes_no_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)

    code, out = mirror.run(capsys, "sync", "--dry-run")

    assert code == 0, out
    assert f"{CHANGE}:1" in out
    assert f"{CHANGE}:2" in out
    assert mirror.board.writes() == []
    assert not (mirror.change_dir / "tracker.yaml").exists()


def test_a_first_pass_announces_the_backfill_and_runs_within_the_cap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # One change item and thirty-nine group items: forty to create, ten at a time.
    mirror = Mirror(tmp_path, groups=39, create_cap=10)

    code, out = mirror.run(capsys, "sync")

    assert code == 0, out
    assert len(mirror.board.made("create")) == 10
    lines = out.splitlines()
    assert f"{APP}: first pass, a backfill of 40 items is expected" in lines
    assert f"{APP}: 30 remain for later ticks" in lines


def test_the_json_form_counts_what_was_expected_made_and_left(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path, groups=39, create_cap=10)

    result = mirror.run_json(capsys, "sync")["repos"][APP]

    assert (result["expected"], result["created"], result["remaining"]) == (40, 10, 30)


def test_one_repos_failure_is_reported_and_the_next_repo_still_syncs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path, platform=True)
    mirror.factory_failures = 1

    result = mirror.run_json(capsys, "sync")["repos"]

    assert "could not be built" in result[APP]["error"]
    assert "error" not in result["platform"]


def test_the_push_calls_come_before_the_pulls_reads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    mirror.board.as_identity("alice@example.test").create("task", "Added by a person")

    code, out = mirror.run(capsys, "sync")

    assert code == 0, out
    names = [call.name for call in mirror.board.calls]
    assert "changed_since" in names
    assert "create" in names
    last_push = max(i for i, name in enumerate(names) if name in {"create", "update"})
    assert last_push < names.index("changed_since")
