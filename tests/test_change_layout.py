"""Where a change lives, for a caller that holds a root and a specs directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.installation import Installation, changes_dir_under


@pytest.mark.parametrize("specs_dir", ["openspec", "specs-store", "docs/specs"])
def test_the_changes_are_under_the_specs_directory(tmp_path: Path, specs_dir: str) -> None:
    assert changes_dir_under(tmp_path, specs_dir) == tmp_path / specs_dir / "changes"


@pytest.mark.parametrize("specs_dir", ["openspec", "specs-store"])
def test_an_installation_lays_its_changes_out_the_same_way(
    tmp_path: Path, specs_dir: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = WorkspaceConfig.model_validate(
        {"version": 1, "repos": {}, "planning": {"specs_dir": specs_dir}}
    )
    installation = Installation(config, tmp_path)

    assert installation.changes_dir == changes_dir_under(installation.root, specs_dir)
