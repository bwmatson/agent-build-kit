"""The planning ignore block holds the lock files of a change and the tracking folder, once."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.init.scaffold import draft_config, write_planning_repo
from tests.factories import fake_openspec, init_repo, recognised_planning
from tests.init.test_scaffold import detection
from tests.init.test_scaffold_in_repo import IGNORE_BLOCK, lay_out

LOCKS = "*.md.lock"
TRACKING = "runs/changes/"


@pytest.fixture(autouse=True)
def data_home(data: Path) -> Path:
    return data


def lines_of(path: Path) -> list[str]:
    return [line.strip() for line in (path / ".gitignore").read_text().splitlines()]


def test_a_new_planning_repo_ignores_lock_files_and_the_tracking_folder_once(
    tmp_path: Path,
) -> None:
    planning = recognised_planning(tmp_path / "planning")
    config = draft_config({"app": detection("app", tmp_path)}, planning_dir=planning)

    write_planning_repo(planning, config, run_openspec=fake_openspec)
    write_planning_repo(planning, config, run_openspec=fake_openspec)

    assert lines_of(planning).count(LOCKS) == 1
    assert lines_of(planning).count(TRACKING) == 1


def test_an_in_repo_block_holds_lock_files_once_after_a_second_run(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")

    lay_out(repo)
    lay_out(repo)

    block = IGNORE_BLOCK.search((repo / ".gitignore").read_text())
    assert block
    assert block["lines"].split().count(LOCKS) == 1


def test_a_block_written_before_gains_the_lock_line_on_a_rerun(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")
    lay_out(repo)
    ignore = repo / ".gitignore"
    ignore.write_text(ignore.read_text().replace(f"{LOCKS}\n", ""))

    lay_out(repo)

    assert lines_of(repo).count(LOCKS) == 1
