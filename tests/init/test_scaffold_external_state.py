"""An in-repo installation's state is outside the repository, so `abk init` writes none of it
into the repository (spec: planning-state-external-checks)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.init.scaffold import missing_state_ignores
from tests.config_migrate_machine_support import TILDE
from tests.factories import init_repo
from tests.init.test_scaffold_in_repo import BLOCK_LINES, IGNORE_BLOCK, ORIENTATION, lay_out


@pytest.fixture(autouse=True)
def data_home(data: Path) -> Path:
    return data


def test_no_state_file_is_written_into_the_repository(tmp_path: Path, data: Path) -> None:
    repo = init_repo(tmp_path / "app")

    lay_out(repo)

    assert not (repo / "runs").exists()
    assert not (data / "app" / "planning" / "state" / "units.json").exists()


def test_the_gitignore_block_has_no_state_line_and_keeps_the_local_files(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "app")

    lay_out(repo)

    block = IGNORE_BLOCK.search((repo / ".gitignore").read_text())
    assert block
    lines = set(block["lines"].split())
    assert BLOCK_LINES <= lines
    assert not [line for line in lines if line.startswith("runs/")]


def test_the_orientation_names_the_resolved_state_and_page_paths(
    tmp_path: Path, data: Path
) -> None:
    repo = init_repo(tmp_path / "app")

    lay_out(repo)

    block = ORIENTATION.search((repo / "AGENTS.md").read_text())
    assert block
    state = data / "app" / "planning" / "state"
    assert str(state) in block[0]
    assert str(state / "pages" / "unit_graph.md") in block[0]


def test_an_outside_state_has_no_ignore_lines_missing() -> None:
    assert missing_state_ignores("", f"{TILDE}s") == []
