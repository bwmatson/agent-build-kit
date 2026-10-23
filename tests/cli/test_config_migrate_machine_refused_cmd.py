"""`abk config --migrate` refuses what it cannot move safely, naming the key and the file, and
leaves nothing behind."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.config_migrate_fakes import beside, run_migrate
from tests.cli.config_migrate_machine_fakes import MACHINE, head, tracked
from tests.factories import git

ANCHOR = MACHINE.replace("  app:\n", "  app: &app\n", 1)
FLOW = (
    "version: 1\n"
    "repos:\n"
    "  app: {slug: example/app, profile: python-uv, path: ../app}\n"
    "project_limits:\n"
    "  max_concurrent_stacks: 2\n"
)
MERGE = (
    "version: 1\n"
    "shared: &shared\n"
    "  slug: example/app\n"
    "  profile: python-uv\n"
    "repos:\n"
    "  app:\n"
    "    <<: *shared\n"
    "    path: ../app\n"
)
BROKEN = "repos: [unclosed\n"
ABK_LOCAL = "abk.local.yaml"


@pytest.mark.parametrize("text", [ANCHOR, FLOW, MERGE], ids=["anchor", "flow", "merge-key"])
def test_an_unsafe_block_exits_2_naming_the_key_and_the_file_and_leaves_nothing(
    text: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tracked(tmp_path, text)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 2
    assert "repos.app" in terminal.err
    assert "abk.yaml" in terminal.err
    assert terminal.asked == 0
    assert path.read_text() == text
    assert beside(path) == [".git"]


def test_a_local_file_that_does_not_parse_exits_2_naming_it_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path, local=BROKEN)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 2
    assert ABK_LOCAL in terminal.err
    assert path.read_text() == MACHINE
    assert (tmp_path / ABK_LOCAL).read_text() == BROKEN
    assert beside(path) == [".git", ABK_LOCAL]


def test_a_tracked_local_file_exits_2_naming_the_command_that_untracks_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path, local="project_limits:\n  max_concurrent_stacks: 4\n")
    git(tmp_path, "add", ABK_LOCAL)
    git(tmp_path, "commit", "-q", "-m", "local")
    before = head(tmp_path)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 2
    assert f"git rm --cached {ABK_LOCAL}" in terminal.err
    assert path.read_text() == MACHINE
    assert head(tmp_path) == before
    assert beside(path) == [".git", ABK_LOCAL]
