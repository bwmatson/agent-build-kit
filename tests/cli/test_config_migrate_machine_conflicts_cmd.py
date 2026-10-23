"""A machine setting the local file already sets is left in abk.yaml and reported."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.config_migrate_fakes import beside, run_migrate
from tests.cli.config_migrate_machine_fakes import CONFLICT, MACHINE, merged, tracked

SET = "repos:\n  app:\n    path: ~/code/app\n"
ONLY_PATH = "version: 1\nrepos:\n  app:\n    slug: example/app\n    path: ../app\n"


def test_a_local_path_keeps_its_key_in_both_files_and_the_others_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path, local=SET)

    code, terminal = run_migrate(capsys, monkeypatch, path, "--yes")

    assert code == 0
    assert CONFLICT in terminal.out
    assert "path: ../app" in path.read_text()
    assert "project_limits" not in path.read_text()
    local = (tmp_path / "abk.local.yaml").read_text()
    assert "path: ~/code/app" in local
    assert "../app" not in local
    assert "project_limits" in local
    assert merged(path.read_text(), local) == merged(MACHINE, SET)


def test_only_conflicting_settings_print_the_reports_and_write_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tracked(tmp_path, ONLY_PATH, local=SET)

    code, terminal = run_migrate(capsys, monkeypatch, path, answers=())

    assert code == 0
    assert terminal.asked == 0
    assert CONFLICT in terminal.out
    assert "nothing needed migrating" in terminal.out
    assert path.read_text() == ONLY_PATH
    assert (tmp_path / "abk.local.yaml").read_text() == SET
    assert beside(path) == [".git", "abk.local.yaml"]
