"""The planning prompt shows the project a group resolved to, and says it was resolved."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.planner import build_prompt
from tests.project_workspace import app_with_projects, tasks_editing


def heading_line(tmp_path: Path, heading: str, path: str, title: str) -> str:
    app_with_projects(tmp_path, "web")
    prompt = build_prompt({"feature": tasks_editing((heading, path))}, [])
    return next(line for line in prompt.splitlines() if line.startswith("## 1.") and title in line)


def test_a_resolved_group_is_shown_with_its_project_and_marked_resolved(tmp_path: Path) -> None:
    line = heading_line(tmp_path, "[app] [unit-test] Build the page", "web/src/a.ts", "Build")

    assert "(project web" in line
    assert "resolved" in line


def test_an_explicit_root_group_is_marked_so(tmp_path: Path) -> None:
    line = heading_line(tmp_path, "[app/<root>] [unit-test] Stay put", "web/src/a.ts", "Stay")

    assert "explicit root" in line
