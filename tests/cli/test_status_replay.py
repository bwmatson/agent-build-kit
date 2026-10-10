"""`abk status` says how many cassettes wait for review, for a repository that records."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.cli.replay_driver import replay_repo, store
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.replay.support import waiting_cassette


def status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    section: bool,
) -> list[str]:
    repo, directory = replay_repo(tmp_path / "app", section=section)
    store(
        directory,
        waiting_cassette("tests/test_a.py::test_one", 0),
        waiting_cassette("tests/test_a.py::test_one", 3, path="/v1/other"),
        waiting_cassette("tests/test_a.py::test_two", 0, needs_review=False),
    )
    workspace = make_installation(
        tmp_path,
        repos={"app": repo.model_dump(mode="json")},
        planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees")),
    )
    UnitStore(tmp_path / "units.json").upsert([stored_unit("one/1", change="one")])
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    return capsys.readouterr().out.splitlines()


def test_status_prints_the_count_of_cassettes_waiting_for_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status(tmp_path, monkeypatch, capsys, section=True)

    [line] = [line for line in lines if "cassette" in line]
    assert "review" in line
    assert re.search(r"\b2\b", line)


def test_status_says_nothing_for_a_repository_with_no_replay_section(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status(tmp_path, monkeypatch, capsys, section=False)

    assert not [line for line in lines if "cassette" in line]
