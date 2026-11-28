"""`abk tests report`: the figures of a repository's tests, printed with their definitions."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli.tests_cmd import cmd_tests_report
from agent_build_kit.installation import load_installation
from agent_build_kit.pipeline.shell import git
from agent_build_kit.pipeline.suite_shape import definition
from tests.cli.e2e_hold_fakes import abk, planning
from tests.factories import init_repo

NOW = datetime(2026, 11, 27, 12, tzinfo=UTC)
WIDE_WINDOW_START = "2026-11-01"
TEST = "def test_a():\n    assert 1\n"


def commit_at(repo: Path, when: str, files: dict[str, str]) -> None:
    for name, content in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(content)
    git(repo, "add", "-A")
    stamped = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when}
    git(repo, "commit", "-qm", "work", env=stamped)


@pytest.fixture
def config(tmp_path: Path) -> Path:
    """An installation of repos `app` (a module, its test file and two more) and `platform`,
    both real repositories with their history in October and November."""
    app = init_repo(tmp_path / "app")
    commit_at(
        app,
        "2026-10-01T10:00:00+00:00",
        {
            "src/app/store.py": "def store():\n    return 1\n",
            "tests/test_store.py": TEST,
            "tests/test_store_lease.py": TEST,
        },
    )
    commit_at(app, "2026-11-10T10:00:00+00:00", {"tests/test_early.py": TEST})
    commit_at(app, "2026-11-22T10:00:00+00:00", {"tests/test_store_more.py": TEST})
    platform = init_repo(tmp_path / "platform")
    commit_at(platform, "2026-10-01T10:00:00+00:00", {"tests/test_other.py": TEST})
    return planning(tmp_path, "", platform_tests="")


def test_report_for_a_repo_prints_its_five_figures_each_with_its_definition(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = abk(
        config, capsys, "tests", "report", "--repo", "app", "--since", WIDE_WINDOW_START
    )
    shown = "\n".join(out)

    assert code == 0, err
    assert all(definition(number) in shown for number in range(1, 6))
    assert "3 of 4" in shown  # figure 1: all but test_store.py are not placed
    assert "2 of 2" in shown  # figure 2: both files added since the date are not for a new module
    assert "platform" not in shown


def test_report_without_a_repo_prints_a_block_for_each_configured_repo(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = abk(config, capsys, "tests", "report", "--since", WIDE_WINDOW_START)
    shown = "\n".join(out)

    assert code == 0, err
    assert shown.count(definition(1)) == 2
    assert "app" in shown
    assert "platform" in shown


def test_report_window_starts_seven_days_before_today_by_default(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    installation = load_installation(config)

    code = cmd_tests_report(argparse.Namespace(repo="app", since=None), installation, now=NOW)

    shown = capsys.readouterr().out
    assert code == 0
    assert "1 of 1" in shown  # only the file added on the 22nd is in the window of 20 to 27


def test_report_for_an_unknown_repo_exits_non_zero_naming_the_configured_ones(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = abk(config, capsys, "tests", "report", "--repo", "nope")
    said = "\n".join([*out, *err])

    assert code != 0
    assert "app" in said
    assert "platform" in said


def test_report_with_a_date_that_does_not_parse_exits_non_zero_naming_it(
    config: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = abk(config, capsys, "tests", "report", "--since", "not-a-date")

    assert code != 0
    assert "not-a-date" in "\n".join([*out, *err])
