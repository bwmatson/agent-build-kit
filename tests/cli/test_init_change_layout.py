"""`abk init` finds an existing change through the one layout function."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from tests.cli.init_quiet import app_repo, quiet
from tests.factories import git, recognised_planning


def test_a_change_the_layout_function_finds_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    quiet(monkeypatch)
    changes = tmp_path / "elsewhere" / "changes"
    for name in ("app-code-standards", "app-testing-infrastructure"):
        (changes / name).mkdir(parents=True)
    monkeypatch.setattr(init_cmd, "changes_dir_under", lambda root, specs_dir: changes)
    monkeypatch.setattr(
        init_cmd, "propose", lambda *a, **k: pytest.fail("proposed a change that exists")
    )
    planning = recognised_planning(tmp_path / "planning")
    git(planning, "init", "-q", "-b", "main")

    code = main(
        ["init", str(planning), "--repo", str(app_repo(tmp_path)), "--yes", "--skip-research"]
    )

    assert code == 0
    assert "kept" in capsys.readouterr().out
