"""`abk init` writes the roles under the runtime it configures, not in a top-level `models:` block
(spec: runtime-models)."""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_build_kit.config import load
from agent_build_kit.init.scaffold import draft_config, write_planning_repo
from tests.factories import fake_openspec, recognised_planning
from tests.init.test_scaffold import detection

ROLES = ("implement", "rework", "review", "rework_review", "regression")


def written_file(tmp_path: Path) -> Path:
    planning = recognised_planning(tmp_path / "planning")
    config = draft_config({"app": detection("app", tmp_path)}, planning_dir=planning)
    write_planning_repo(planning, config, run_openspec=fake_openspec)
    return planning / "abk.yaml"


def test_the_written_file_holds_the_roles_under_the_runtime(tmp_path: Path) -> None:
    path = written_file(tmp_path)
    document = yaml.safe_load(path.read_text())

    models = document["runtimes"]["claude_code"]["models"]

    assert set(models) == set(ROLES)
    assert "models" not in document
    assert not [line for line in path.read_text().splitlines() if line.startswith("models:")]
    assert all(isinstance(name, str) and name for name in models.values())


def test_the_written_file_loads_with_the_runtimes_own_default_names(tmp_path: Path) -> None:
    own = load(written_file(tmp_path)).runtimes["claude_code"].models

    assert [getattr(own, role) for role in ROLES] == [
        "sonnet",
        "sonnet",
        "opus",
        "opus",
        "opus",
    ]
