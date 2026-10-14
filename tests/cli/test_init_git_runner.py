"""`abk init` reads and commits the planning repository through the shared git runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from tests.cli.init_quiet import app_repo, quiet
from tests.factories import git, recognised_planning
from tests.git_runner_spy import spy_on_git

FLAGS = ["--yes", "--skip-research", "--skip-propose"]


@pytest.fixture(autouse=True)
def quiet_init(monkeypatch: pytest.MonkeyPatch) -> None:
    quiet(monkeypatch)


def planning_repo(root: Path) -> Path:
    planning = recognised_planning(root / "planning")
    git(planning, "init", "-q", "-b", "main")
    git(planning, "config", "user.email", "t@t.t")
    git(planning, "config", "user.name", "t")
    git(planning, "add", "-A")
    git(planning, "commit", "-qm", "base")
    return planning


def test_the_tree_is_read_and_committed_through_the_shared_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planning = planning_repo(tmp_path)
    spy = spy_on_git(monkeypatch, init_cmd)

    code = main(["init", str(planning), "--repo", str(app_repo(tmp_path)), *FLAGS])

    assert code == 0
    assert spy.calls[0] == ("status", "--porcelain")
    assert ("add", "-A") in spy.calls
    assert any(args[:2] == ("commit", "-q") for args in spy.calls)
    assert "abk init: workspace app" in git(planning, "log", "--oneline")


def test_a_commit_that_fails_is_reported_with_what_git_said(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    planning = planning_repo(tmp_path)
    spy_on_git(monkeypatch, init_cmd, failing={"commit": "fatal: no identity"})

    code = main(["init", str(planning), "--repo", str(app_repo(tmp_path)), *FLAGS])

    assert code == 0
    assert "not committed: fatal: no identity" in capsys.readouterr().out


def test_a_failed_add_is_reported_and_no_commit_is_tried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    planning = planning_repo(tmp_path)
    spy = spy_on_git(monkeypatch, init_cmd, failing={"add": "fatal: cannot add"})

    main(["init", str(planning), "--repo", str(app_repo(tmp_path)), *FLAGS])

    assert "not committed: fatal: cannot add" in capsys.readouterr().out
    assert "commit" not in spy.subcommands()
