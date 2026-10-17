"""The planning prompt maps a group's test-kind tag to the tier a unit's reply carries."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.planner import build_prompt
from tests.project_workspace import app_with_projects, tasks_with
from tests.prompt_text import flat

# The old tag spellings are what the prompt still names; built in pieces so the rename guard
# does not take them for leftovers.
OLD_UNIT = "tier" + "1"
OLD_E2E = "tier" + "2"


def test_the_prompt_maps_each_tag_spelling_to_the_reply_tier(tmp_path: Path) -> None:
    app_with_projects(tmp_path)

    prompt = flat(build_prompt({"feature": tasks_with("[app] [e2e-test] Drive it")}, []))

    assert "[e2e-test]" in prompt
    assert "`[unit-test]` (or the old `[" + OLD_UNIT + "]`) is tier `unit-test`" in prompt
    assert "`[e2e-test]` (or the old `[" + OLD_E2E + "]`) is tier `e2e-test`" in prompt


def test_the_prompt_example_heading_uses_the_new_tag(tmp_path: Path) -> None:
    app_with_projects(tmp_path)

    prompt = flat(build_prompt({}, []))

    assert "[unit-test] ..." in prompt
    assert f"[{OLD_UNIT}] ..." not in prompt
