"""A group heading is tagged `[unit-test]` or `[e2e-test]`; `[tier1]` and `[tier2]` are read
as the same kinds, with a notice (spec: test-kind-names-are-accepted-both-ways)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.work_graph import TaskGroup, ValidationError, validate_tasks
from tests.cli.replan_driver import Replan, tagged_md


def read(tmp_path: Path, *tags: str) -> tuple[list[TaskGroup], list[ValidationError]]:
    (tmp_path / "tasks.md").write_text(tagged_md(*tags))
    return validate_tasks(tmp_path / "tasks.md")


def test_the_new_tags_are_read_as_the_two_test_kinds(tmp_path: Path) -> None:
    groups, errors = read(tmp_path, "unit-test", "e2e-test")

    assert errors == []
    assert [g.tier for g in groups] == [TestTier.UNIT_TEST, TestTier.E2E_TEST]


def test_the_old_tags_are_read_as_the_same_kinds(tmp_path: Path) -> None:
    groups, errors = read(tmp_path, "tier1", "tier2")

    assert errors == []
    assert [g.tier for g in groups] == [TestTier.UNIT_TEST, TestTier.E2E_TEST]


def test_an_unknown_tag_is_refused_listing_the_new_spellings(tmp_path: Path) -> None:
    groups, errors = read(tmp_path, "integration")

    assert groups == []
    (error,) = errors
    assert "integration" in error.message
    assert "unit-test" in error.message
    assert "e2e-test" in error.message


def test_tags_prints_a_notice_for_each_old_tag_with_the_new_tag_and_the_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tagged_md("tier1", "tier2", "tier2"))

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), run.inst)

    notices = [line for line in capsys.readouterr().out.splitlines() if "deprecated" in line]
    assert status == 0
    assert len(notices) == 3
    assert "group 1" in notices[0] and "[unit-test]" in notices[0]
    assert "group 2" in notices[1] and "[e2e-test]" in notices[1]
    assert "group 3" in notices[2] and "[e2e-test]" in notices[2]


def test_tags_prints_the_new_spellings_for_both_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tagged_md("unit-test", "e2e-test"))

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), run.inst)

    out = capsys.readouterr().out
    assert status == 0
    assert "[app] [unit-test] Group 1" in out
    assert "[app] [e2e-test] Group 2" in out
    assert "deprecated" not in out


def test_check_prints_a_notice_for_each_old_tag_and_none_for_a_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tagged_md("tier1", "e2e-test", "tier2"))
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    status = cli.cmd_check(argparse.Namespace(), run.inst)

    notices = [line for line in capsys.readouterr().out.splitlines() if "deprecated" in line]
    assert status == 0
    assert len(notices) == 2
    assert "group 1" in notices[0] and "group 3" in notices[1]
