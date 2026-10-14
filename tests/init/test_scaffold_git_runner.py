"""The scaffold makes the planning repository through the shared git runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.init import scaffold
from agent_build_kit.init.scaffold import ScaffoldError, draft_config, write_planning_repo
from tests.factories import recognised_planning
from tests.git_runner_spy import spy_on_git


def fake_openspec(argv, *, cwd, **kwargs):
    (cwd / "openspec" / "changes").mkdir(parents=True)
    (cwd / "openspec" / "config.yaml").write_text("schema: spec-driven\n")
    return subprocess.CompletedProcess(argv, 0, "", "")


def test_the_repository_is_initialised_through_the_shared_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planning = recognised_planning(tmp_path / "planning")
    config = draft_config({}, planning_dir=planning)
    spy = spy_on_git(monkeypatch, scaffold)

    write_planning_repo(planning, config, run_openspec=fake_openspec)

    assert spy.calls[0] == ("init", "-q", "-b", "main")
    assert (planning / ".git").is_dir()


def test_a_failed_init_is_reported_with_what_git_said(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planning = recognised_planning(tmp_path / "planning")
    config = draft_config({}, planning_dir=planning)
    spy_on_git(monkeypatch, scaffold, failing={"init": "fatal: cannot init"})

    with pytest.raises(ScaffoldError, match=r"git init failed in .*: fatal: cannot init"):
        write_planning_repo(planning, config, run_openspec=fake_openspec)
