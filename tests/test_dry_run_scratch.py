"""A case's `DryRun` is found by the failure dump of every test that takes it as a fixture."""

from __future__ import annotations

from pathlib import Path

from tests.dry_scratch import DryRun


def a_run(root: Path) -> DryRun:
    return DryRun(
        change="add-page-path",
        branch="spec/add-page-path/1",
        app=root / "app",
        remote=root / "remote.git",
        planning=root / "planning",
        state=root / "state",
        record=root / "agent-lines.jsonl",
        env={},
    )


def test_a_run_is_its_own_scratch_so_the_dump_finds_it_through_the_fixture_value(
    tmp_path: Path,
) -> None:
    run = a_run(tmp_path)

    assert run.scratch is run
    assert run.scratch.state == run.state
