"""The planner is told not to close a cycle with work in flight (spec:
planned-dependencies-never-close-a-cycle). The prompt is advice; the drop is the guarantee."""

from __future__ import annotations

import json

from agent_build_kit.pipeline.planner import plan_round


def prompt_with_an_unstarted_unit_in_flight() -> str:
    captured: dict[str, str] = {}

    def fake_claude(prompt: str) -> str:
        captured["prompt"] = prompt
        return json.dumps({"units": [], "joins": []})

    plan_round(
        changes={"add-marker": "## 1. [app] [tier1] Register the marker\n"},
        in_flight=[
            {
                "id": "other/1",
                "repo": "app",
                "branch": "spec/other/1",
                "state": "planned",
                "unstarted": True,
                "tier": "tier1",
                "estimated_lines": 100,
                "builds": "1",
                "depends_on": [],
            }
        ],
        run_claude=fake_claude,
    )
    return captured["prompt"]


def test_the_prompt_says_an_unstarted_unit_must_not_depend_on_the_change_being_planned() -> None:
    prompt = prompt_with_an_unstarted_unit_in_flight()

    rule = [
        paragraph
        for paragraph in prompt.split("\n\n")
        if "unstarted" in paragraph
        and "must not" in paragraph
        and "change being planned" in paragraph
    ]
    assert rule, "no rule against giving an unstarted unit a dependency on this change"
    assert "through" in rule[0], "the rule covers a dependency through other units"
