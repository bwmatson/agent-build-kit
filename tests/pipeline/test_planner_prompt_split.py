"""The planning prompt states the one-split rule and shows each group's and unit's split."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit.pipeline.planner import build_prompt, in_flight_item
from agent_build_kit.pipeline.work_graph import validate_tasks
from tests.factories import stored_unit
from tests.prompt_text import flat
from tests.split_workspace import group, splits_workspace, tasks_text


def test_the_prompt_says_a_unit_is_in_one_split_and_a_join_never_crosses_splits(
    tmp_path: Path,
) -> None:
    splits_workspace(tmp_path / "planning")

    text = flat(build_prompt({"feature": tasks_text(group(1))}, [])).lower()

    assert "one e2e-test split" in text
    assert "groups of different splits are never in one unit" in text
    assert "a join never crosses splits" in text
    assert "the same e2e-test split" in text


def test_a_group_outside_rest_is_shown_with_its_split_and_one_in_rest_is_not(
    tmp_path: Path,
) -> None:
    splits_workspace(tmp_path / "planning")
    tasks = tasks_text(group(1, "Split: claude_code"), group(2, "Split: acp"), group(3))
    (tmp_path / "tasks.md").write_text(tasks)
    groups, _ = validate_tasks(tmp_path / "tasks.md")

    prompt = build_prompt({"feature": tasks}, [], groups=groups)

    headings = [line for line in prompt.splitlines() if re.match(r"## \d+\. \[app\]", line)]
    assert len(headings) == 3
    assert "(split claude_code)" in headings[0]
    assert "(split acp)" in headings[1]
    assert "(split" not in headings[2]


def test_the_line_of_an_unstarted_unit_names_its_split_unless_it_is_rest(tmp_path: Path) -> None:
    splits_workspace(tmp_path / "planning")
    acp = stored_unit("base/1", change="base", tier="e2e-test", split="acp")
    plain = stored_unit("base/2", change="base", tier="e2e-test")

    prompt = build_prompt(
        {"feature": tasks_text(group(1))}, [in_flight_item(acp), in_flight_item(plain)]
    )

    first, second = (line for line in prompt.splitlines() if line.startswith("- base/"))
    assert "split acp" in first
    assert "split" not in second
