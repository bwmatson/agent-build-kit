"""`abk init` looks for an existing change under the configured `planning.specs_dir`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from tests.cli.init_quiet import app_repo, quiet
from tests.factories import recognised_planning

FLAGS = ["--yes", "--skip-research"]


def test_an_existing_change_is_looked_for_and_reported_under_the_configured_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    quiet(monkeypatch)
    for name in ("NAME", "EMAIL"):
        monkeypatch.setenv(f"GIT_AUTHOR_{name}", "t")
        monkeypatch.setenv(f"GIT_COMMITTER_{name}", "t")
    monkeypatch.setattr(
        init_cmd, "propose", lambda *a, **k: pytest.fail("proposed a change that exists")
    )
    planning = recognised_planning(tmp_path / "planning")
    argv = ["init", str(planning), "--repo", str(app_repo(tmp_path)), *FLAGS]
    assert main([*argv, "--skip-propose"]) == 0
    config = planning / "abk.yaml"
    config.write_text(
        yaml.safe_dump({**yaml.safe_load(config.read_text()), "planning": {"specs_dir": "specs"}})
    )
    for name in ("app-code-standards", "app-testing-infrastructure"):
        (planning / "specs" / "changes" / name).mkdir(parents=True)
    capsys.readouterr()

    assert main(argv) == 0

    out = capsys.readouterr().out
    assert "kept specs/changes/app-code-standards/" in out
    assert "kept openspec/" not in out
