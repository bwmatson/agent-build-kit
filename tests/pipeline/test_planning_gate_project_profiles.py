"""The planning commit's gate checks a `Project:` line against the profiles the installation's
abk.yaml lists, as `abk tags` does (spec: project-lines)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.pipeline.attach import planning_gate
from tests.project_workspace import OPT_OUT, app_with_projects


def gate_says(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, written: str) -> str:
    inst = app_with_projects(tmp_path, "web")  # `app/web` is listed as python-uv
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))
    directory = inst.changes_dir / "feature"
    directory.mkdir(parents=True)
    (directory / "tasks.md").write_text(
        f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [unit-test] Group 1\n\n{written}\n\n"
        "- [ ] 1.1 Test: it.\n"
    )
    return planning_gate(inst, "feature")(tmp_path)


def test_an_add_with_another_profile_than_the_listed_one_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejected = gate_says(tmp_path, monkeypatch, "Project: add web node-npm")

    assert "abk tags" in rejected
    assert "python-uv" in rejected and "node-npm" in rejected


def test_an_add_with_the_listed_profile_passes_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert "abk tags" not in gate_says(tmp_path, monkeypatch, "Project: add web python-uv")
