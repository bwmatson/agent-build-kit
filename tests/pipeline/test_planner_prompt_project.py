"""The planning prompt names each group's project and says a unit never spans projects."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit.pipeline.planner import build_prompt
from tests.project_workspace import app_with_projects, tasks_with
from tests.prompt_text import flat

SHOWN = re.compile(r"project\W+web\b", re.IGNORECASE)


def prompt_for(tmp_path: Path, *paths: str, heading: str) -> str:
    app_with_projects(tmp_path, *paths)
    return build_prompt({"feature": tasks_with(heading)}, [])


def changes_of(prompt: str) -> str:
    return prompt[prompt.index("Changes ready to plan") : prompt.index("Units already in flight")]


def test_a_group_tagged_for_a_project_is_shown_with_that_project(tmp_path: Path) -> None:
    prompt = prompt_for(tmp_path, "web", heading="[app/web] [tier1] Build the page")

    assert SHOWN.search(changes_of(prompt))


def test_the_prompt_says_a_unit_is_in_one_repo_and_one_project(tmp_path: Path) -> None:
    text = flat(prompt_for(tmp_path, "web", heading="[app/web] [tier1] Build the page")).lower()

    assert "one repo and one project" in text
    assert "different projects" in text
    assert (
        "never" in text[text.index("different projects") - 120 : text.index("different projects")]
    )


def test_a_workspace_with_one_project_per_repo_adds_only_the_sentence(tmp_path: Path) -> None:
    prompt = prompt_for(tmp_path, heading="[app] [tier1] Build the page")

    assert "one repo and one project" in flat(prompt).lower()
    assert "## 1. [app] [tier1] Build the page\n" in changes_of(prompt)
    assert "(project" not in changes_of(prompt)
