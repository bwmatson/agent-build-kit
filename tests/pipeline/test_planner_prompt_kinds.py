"""The planning prompt tells the planner which kinds may be joined, and the reply's kinds."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.planner import build_prompt
from tests.project_workspace import app_with_projects
from tests.prompt_text import flat


def test_the_join_rule_says_which_kinds_go_together(tmp_path: Path) -> None:
    app_with_projects(tmp_path)

    prompt = flat(build_prompt({}, []))

    assert "same repo and compatible kinds" in prompt
    assert "same repo and same tier" not in prompt
    assert "`unit-test` and `integration-test` together" in prompt
    assert "`e2e-test` only with `e2e-test`" in prompt


def test_the_schema_example_lists_the_three_kinds(tmp_path: Path) -> None:
    app_with_projects(tmp_path)

    prompt = flat(build_prompt({}, []))

    assert '"tier": "unit-test|integration-test|e2e-test"' in prompt
