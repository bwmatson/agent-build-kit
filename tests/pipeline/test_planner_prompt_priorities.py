"""The planner is shown each group's priority and each in-flight unit's, and the rule that a
unit depends only on code it needs (spec: planner-priorities)."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit.pipeline.planner import build_prompt, in_flight_item
from agent_build_kit.pipeline.units import FAILED
from agent_build_kit.pipeline.work_graph import declared_projects, validate_tasks
from tests.factories import stored_unit
from tests.project_workspace import OPT_OUT, app_with_projects
from tests.prompt_text import flat

PRIORITY = re.compile(r"\(priority (\d)\)")


def tasks_of(
    *lines: int | None, default: int | None = None, heading: str = "[app] [unit-test]"
) -> str:
    """One group per entry, each with that `Priority:` line (none for no line)."""
    text = f"# Tasks\n\n{OPT_OUT}\n"
    text += f"Priority: {default}\n\n" if default is not None else ""
    for number, value in enumerate(lines, start=1):
        text += f"## {number}. {heading} Group {number}\n\n"
        text += f"Priority: {value}\n\n" if value is not None else ""
        text += f"- [ ] {number}.1 Test: it.\n- [ ] {number}.2 Do it.\n\n"
    return text


def prompt_of(tmp_path: Path, tasks: str, in_flight: list[dict] | None = None) -> str:
    """The prompt for `tasks`, shown the groups its own file reads as."""
    inst = app_with_projects(tmp_path, "web")
    path = tmp_path / "tasks.md"
    path.write_text(tasks)
    groups, errors = validate_tasks(
        path, repos=tuple(inst.repos), projects=declared_projects(inst.repos)
    )
    assert not errors
    return build_prompt({"feature": tasks}, in_flight or [], groups=groups)


def headings(prompt: str) -> list[str]:
    return [line for line in prompt.splitlines() if line.startswith("## ")]


def marks(prompt: str) -> list[str]:
    return [found.group(1) if (found := PRIORITY.search(h)) else "" for h in headings(prompt)]


def test_a_group_heading_shows_its_own_priority_else_normal(tmp_path: Path) -> None:
    assert marks(prompt_of(tmp_path, tasks_of(1, None))) == ["1", "3"]


def test_a_group_with_no_line_shows_the_changes_default(tmp_path: Path) -> None:
    assert marks(prompt_of(tmp_path, tasks_of(None, 2, default=4))) == ["4", "2"]


def test_the_priority_comes_before_the_project_and_the_builder_on_the_same_heading(
    tmp_path: Path,
) -> None:
    unit = stored_unit("feature/1", change="feature", groups=(1,), state=FAILED)
    tasks = tasks_of(1, heading="[app/web] [unit-test]")

    prompt = prompt_of(tmp_path, tasks, [in_flight_item(unit, [unit])])

    assert (
        "## 1. [app/web] [unit-test] Group 1 (priority 1) (project web) (built by feature/1)"
        in prompt.splitlines()
    )


def test_lines_that_are_not_headings_are_left_alone(tmp_path: Path) -> None:
    tasks = tasks_of(1, 2)

    prompt = prompt_of(tmp_path, tasks)

    body = [line for line in tasks.splitlines() if line and not line.startswith("## ")]
    assert all(line in prompt.splitlines() for line in body)
    assert prompt.count("(priority") == 2


def test_an_unstarted_and_a_started_unit_are_listed_with_their_priority() -> None:
    unstarted = stored_unit("feature/1", change="feature", groups=(1,), priority=2)
    started = stored_unit("feature/2", change="feature", groups=(2,), priority=2, state=FAILED)

    both = [unstarted, started]
    prompt = build_prompt({}, [in_flight_item(unstarted, both), in_flight_item(started, both)])

    lines = {line.split()[1]: line for line in prompt.splitlines() if line.startswith("- feature/")}
    assert "priority 2" in lines["feature/1"]
    assert "priority 2" in lines["feature/2"]


def test_a_promoted_unit_is_listed_with_its_stored_priority() -> None:
    promoted = stored_unit("feature/1", change="feature", groups=(1,), priority=1)

    item = in_flight_item(promoted, [promoted])

    assert item["priority"] == 1
    assert "priority 1" in build_prompt({}, [item])


def test_a_prompt_built_without_groups_has_no_group_mark_and_lists_priorities(
    tmp_path: Path,
) -> None:
    unit = stored_unit("feature/1", change="feature", groups=(1,), priority=2)

    prompt = build_prompt({"feature": tasks_of(1, 2)}, [in_flight_item(unit, [unit])])

    assert not any(PRIORITY.search(heading) for heading in headings(prompt))
    assert "priority 2" in prompt


def schema_of(prompt: str) -> str:
    return prompt[prompt.index("Respond with exactly this shape") :]


def rule_of(prompt: str) -> str:
    bullets = flat(prompt).split(" - ")
    return next(b for b in bullets if "adjacent" in b)


def test_the_prompt_says_to_depend_only_for_code_a_unit_introduces() -> None:
    rule = rule_of(build_prompt({}, [])).lower()

    assert re.search(r"only[^.]*code[^.]*introduc", rule)
    assert re.search(r"not[^.]*more urgent[^.]*depend[^.]*less urgent[^.]*adjacent", rule)
    assert re.search(r"not[^.]*chain[^.]*independent", rule)
    assert re.search(r"most urgent priority of its groups", rule)


def test_the_rule_names_no_field_the_schema_does_not_list() -> None:
    prompt = build_prompt({}, [])

    named = set(re.findall(r"`(\w+)`", rule_of(prompt)))
    assert named <= set(re.findall(r'"(\w+)"', schema_of(prompt)))


def test_the_prompt_states_when_to_depend_once() -> None:
    flat_prompt = flat(build_prompt({}, []))

    assert flat_prompt.count("Depend on a unit") == 1
    assert "Depend on a unit if" not in flat_prompt
