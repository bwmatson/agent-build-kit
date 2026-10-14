"""The step that opens a pull request finds the change's files through the one layout function."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import active
from agent_build_kit.graph import nodes
from agent_build_kit.installation import changes_dir_under
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh


def test_the_body_is_built_from_the_changes_under_the_planning_specs_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = active()
    custom = config.model_copy(
        update={"planning": config.planning.model_copy(update={"specs_dir": "specs-store"})}
    )
    monkeypatch.setattr(nodes, "active", lambda: custom)
    handed: list[Path] = []
    real = nodes.build_pr_body

    def build_body(*args: Any, changes_dir: Path, **kwargs: Any) -> str:
        handed.append(changes_dir)
        return real(*args, changes_dir=changes_dir, **kwargs)

    monkeypatch.setattr(nodes, "build_pr_body", build_body)
    recorder = fresh(tmp_path)

    build(tmp_path, recorder)

    assert handed
    assert set(handed) == {changes_dir_under(tmp_path / "meta", "specs-store")}
