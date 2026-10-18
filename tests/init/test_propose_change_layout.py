"""The change proposal finds a change's tasks through the one layout function."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.init import propose
from agent_build_kit.init.propose import validation_errors


def valid(argv, *, cwd, **kwargs):
    report = {"items": [{"id": "feature", "type": "change", "valid": True, "issues": []}]}
    return subprocess.CompletedProcess(argv, 0, json.dumps(report), "")


def test_the_tasks_are_read_where_the_layout_function_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes = tmp_path / "elsewhere" / "changes"
    monkeypatch.setattr(propose, "changes_dir_under", lambda root, specs_dir: changes)
    (changes / "feature").mkdir(parents=True)
    (changes / "feature" / "tasks.md").write_text(
        "## 1. [app] [unit-test] First\n\n- [ ] 1.1 Test it\n\n"
        "Acceptance: none — scaffolding only\n"
    )

    errors = validation_errors(tmp_path, "feature", repos=("app",), projects={}, run_openspec=valid)

    assert errors == []


def test_a_custom_specs_directory_is_handed_to_the_layout_function(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[tuple[Path, str]] = []

    def layout(root: Path, specs_dir: str) -> Path:
        asked.append((root, specs_dir))
        return root / specs_dir / "changes"

    monkeypatch.setattr(propose, "changes_dir_under", layout)

    errors = validation_errors(
        tmp_path,
        "feature",
        repos=("app",),
        projects={},
        run_openspec=valid,
        specs_dir="specs-store",
    )

    assert asked == [(tmp_path, "specs-store")]
    assert errors == ["specs-store/changes/feature/tasks.md is missing"]
