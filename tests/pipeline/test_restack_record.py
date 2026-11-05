"""A restack decision is a `restack` line of the usage ledger (spec: restack-points, each
restack decision is recorded and summarised). The record is written directly, and by the
moved-base run, whose command runner is the faked boundary."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.wiring import build_unit_test
from tests.fake_clock import install
from tests.moved_base_fakes import Profile, moved, passing, restack_lines


def test_a_restack_line_carries_every_field_it_is_given(
    workspace: Installation,
) -> None:
    told: list[str] = []

    spans.record_restack(
        spans.RestackRecord(
            at="2030-01-01T09:00:00+00:00",
            unit="feature/1",
            change="feature",
            point="before_pr",
            moved=True,
            moved_from="abc123",
            changelog=1,
            documents=2,
            tests=3,
            code=4,
            outcome="clean",
            retest="full",
            retest_seconds=960.0,
            retest_result="passed",
        ),
        told.append,
    )

    (line,) = restack_lines(workspace)
    assert line["unit"] == "feature/1"
    assert line["point"] == "before_pr"
    assert (line["moved"], line["moved_from"]) == (True, "abc123")
    assert [line[kind] for kind in ("changelog", "documents", "tests", "code")] == [1, 2, 3, 4]
    assert line["outcome"] == "clean"
    assert (line["retest"], line["retest_seconds"], line["retest_result"]) == (
        "full",
        960.0,
        "passed",
    )
    assert not told


def test_a_resolution_records_the_time_it_took(workspace: Installation) -> None:
    spans.record_restack(
        spans.RestackRecord(
            at="2030-01-01T09:00:00+00:00",
            unit="feature/1",
            point="before_review",
            moved=True,
            outcome="resolved",
            resolution_seconds=412.5,
        ),
        lambda message: None,
    )

    (line,) = restack_lines(workspace)
    assert (line["outcome"], line["resolution_seconds"]) == ("resolved", 412.5)
    assert line["retest"] == "none"


def test_a_base_that_did_not_move_is_recorded_as_not_moved(workspace: Installation) -> None:
    spans.record_restack(
        spans.RestackRecord(
            at="2030-01-01T09:00:00+00:00", unit="feature/1", point="prepare", moved=False
        ),
        lambda message: None,
    )

    (line,) = restack_lines(workspace)
    assert (line["point"], line["moved"], line["moved_from"]) == ("prepare", False, "")


def test_the_moved_base_run_records_the_files_it_was_given_by_kind_and_its_retest(
    tmp_path: Path, workspace: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = install(monkeypatch)
    repo, old_base = moved(
        tmp_path,
        own={"a.py": "a = 2\n"},
        incoming={"b.py": "b = 2\n", "CHANGELOG.md": "# log\n", "docs/x.md": "x\n"},
    )

    ran: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        ran.append(command)
        clock.advance(12.5)
        return passing(command)

    passed, _ = build_unit_test(
        profile=Profile(), run=run, log=lambda message: None, repo=RepoConfig(path=repo)
    )(cwd=repo, base="main", moved_from=old_base)

    assert passed
    (line,) = restack_lines(workspace)
    assert line["moved"] is True
    assert line["moved_from"] == old_base
    assert (line["changelog"], line["documents"], line["code"]) == (1, 1, 1)
    assert line["outcome"] == "clean"
    assert line["retest_result"] == "passed"
    assert ran and line["retest_seconds"] == 12.5 * len(ran), "the time every command took"
