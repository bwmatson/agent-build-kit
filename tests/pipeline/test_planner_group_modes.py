"""The planner gives a build mode for each group, never below the group's floor
(spec: group-build-modes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.planner import PlannerError, parse_graph, plan_round
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.cli.replan_driver import Replan, answer, planned
from tests.factories import groups_at, stored_unit

CODE_TASK = "Edit `src/pkg/foo.py` to add it."
DOC_TASK = "Update `docs/guide.md` and `CHANGELOG.md`."


def groups(*free: bool) -> list[TaskGroup]:
    """One group per entry; `free` marks the groups that name only documents."""
    return [
        group.model_copy(update={"code_free": code_free})
        for group, code_free in zip(groups_at(*[3] * len(free)), free, strict=True)
    ]


def tasks_text(*bodies: str) -> str:
    text = "# Tasks\n\n"
    for number, body in enumerate(bodies, start=1):
        text += f"## {number}. [app] [unit-test] Group {number}\n\n- [ ] {number}.1 {body}\n\n"
    return text


def reply(modes: dict[str, str] | None, *numbers: int) -> str:
    record: dict = {
        "id": "feature/1",
        "change": "feature",
        "title": "t",
        "repo": "app",
        "tier": "unit-test",
        "groups": list(numbers),
    }
    if modes is not None:
        record["group_modes"] = modes
    return json.dumps({"units": [record]})


def plan(modes: dict[str, str] | None, *free: bool) -> Unit:
    bodies = tuple(DOC_TASK if is_free else CODE_TASK for is_free in free)
    return parse_graph(
        reply(modes, *range(1, len(free) + 1)), groups=groups(*free), tasks=tasks_text(*bodies)
    )[0]


def prompt() -> str:
    captured: dict[str, str] = {}

    def ask(text: str) -> str:
        captured["prompt"] = text
        return '{"units": []}'

    plan_round(changes={"c": "## 1. [app] [unit-test] x\n"}, in_flight=[], run_claude=ask)
    return captured["prompt"]


def test_the_prompt_asks_for_a_mode_per_group_and_reserves_no_code_for_groups_without_code() -> (
    None
):
    text = prompt()

    for word in ("group_modes", "`tests_and_code`", "`no_code`", "`tests_only`"):
        assert word in text
    assert "touches no code" in text


def test_a_no_code_reply_for_a_group_that_may_be_no_code_is_stored_by_change_and_group() -> None:
    unit = plan({"1": "no_code"}, True)

    assert unit.group_modes == {"feature/1": "no_code"}


def test_a_mode_below_the_floor_is_refused_naming_the_unit_and_group() -> None:
    with pytest.raises(PlannerError) as refused:
        plan({"1": "no_code"}, False)

    message = str(refused.value)
    assert "feature/1" in message
    assert "group 1" in message
    assert "tests_and_code" in message


def test_a_reply_may_raise_a_group_that_may_be_no_code_to_tests_and_code() -> None:
    assert plan({"1": "tests_and_code"}, True).group_modes == {"feature/1": "tests_and_code"}


def test_an_unknown_mode_is_refused() -> None:
    with pytest.raises(PlannerError, match="no_cod"):
        plan({"1": "no_cod"}, True)


def test_a_reply_with_no_mode_takes_the_floor_of_each_group() -> None:
    unit = plan(None, True, False)

    assert unit.group_modes == {"feature/1": "no_code", "feature/2": "tests_and_code"}


def test_a_reply_naming_a_mode_for_one_group_gives_the_other_its_floor() -> None:
    unit = plan({"1": "tests_and_code"}, True, False)

    assert unit.group_modes == {"feature/1": "tests_and_code", "feature/2": "tests_and_code"}


def test_replan_prints_a_changed_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tasks = (
        "# Tasks\n\nAcceptance: none — a fixture\n\n## 1. [app] [unit-test] Group 1\n\n"
        "- [ ] 1.1 Test: it reads.\n- [ ] 1.2 Update `docs/guide.md`.\n"
    )
    run = Replan(tmp_path, monkeypatch, feature=tasks)
    run.store.upsert(
        [
            stored_unit(
                "feature/1",
                change="feature",
                groups=(1,),
                group_modes={"feature/1": "tests_and_code"},
            )
        ]
    )
    run.record("feature")
    unit = {**planned("feature/1", (1,)), "group_modes": {"1": "no_code"}}

    code, out = run.run(capsys, "feature", reply=answer(unit))

    assert code == 0, out
    line = next(ln for ln in out.splitlines() if "feature/1" in ln and "mode" in ln)
    assert "tests_and_code" in line and "no_code" in line
