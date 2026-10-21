"""A stubbed build commits a test-only group's tests alone: no implementation call is made for
it, and the build goes on to the next group or to the checks (spec: test-only-groups)."""

from __future__ import annotations

import re
from pathlib import Path

from tests.graph.branch_fakes import built, subjects
from tests.graph.test_per_group_build import STEPS, group_named

PARSE = {1: ("Parse the key", ""), 2: ("Drive the stack", "")}
THREE = {1: ("G1", ""), 2: ("G2", ""), 3: ("G3", "")}


def agent_calls(events: list[str]) -> list[str]:
    return [event for event in events if event.startswith("claude:")]


def test_an_ordinary_group_then_a_test_only_group_gives_three_agent_calls(tmp_path: Path) -> None:
    recorder, outcome, repo = built(tmp_path, groups={"add-marker": PARSE}, e2e=(2,))

    assert outcome.status == "open"
    assert agent_calls(recorder.events) == ["claude:tests", "claude:impl", "claude:tests"]
    assert [group_named(prompt) for prompt in recorder.prompts[:3]] == ["1", "1", "2"]
    assert subjects(repo) == ["test: Parse the key", "feat: Parse the key", "test: Drive the stack"]
    built_steps = [event for event in recorder.events if event in STEPS]
    assert built_steps == [
        *["claude:tests", "stub-checks", "commit:test", "claude:impl", "commit:feat"],
        *["claude:tests", "stub-checks", "commit:test"],
    ]
    assert recorder.events.index("unit-test") > recorder.events.index("commit:test", 4)
    assert "review" in recorder.events


def test_the_tests_prompt_of_a_test_only_group_says_what_the_group_does_not_do(
    tmp_path: Path,
) -> None:
    recorder, _, _ = built(tmp_path, groups={"add-marker": PARSE}, e2e=(2,))

    ordinary, test_only = recorder.prompts[0].lower(), recorder.prompts[2].lower()
    assert "no implementation" in test_only
    assert re.search(r"no stubs|stubs are not needed|need no stubs|not need stubs", test_only)
    assert re.search(r"(not|never) (to )?run[^.]*live", test_only)
    assert "no implementation" not in ordinary
    assert "live" not in ordinary


def test_a_test_only_group_in_the_middle_is_passed_over_by_the_implement_step(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, groups={"add-marker": THREE}, e2e=(2,))

    assert outcome.status == "open"
    assert agent_calls(recorder.events) == [
        *["claude:tests", "claude:impl", "claude:tests", "claude:tests", "claude:impl"]
    ]
    assert [group_named(prompt) for prompt in recorder.prompts[:5]] == ["1", "1", "2", "3", "3"]
    assert subjects(repo) == ["test: G1", "feat: G1", "test: G2", "test: G3", "feat: G3"]


def test_a_unit_of_test_only_groups_makes_one_tests_commit_for_each_and_no_implementation(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, groups={"add-marker": THREE}, e2e=(1, 2, 3))

    assert outcome.status == "open", outcome.detail
    assert agent_calls(recorder.events) == ["claude:tests"] * 3
    assert subjects(repo) == ["test: G1", "test: G2", "test: G3"]
    assert "unit-test" in recorder.events and "review" in recorder.events


def test_a_failing_static_check_on_a_test_only_groups_tests_is_fixed_before_the_commit(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(
        tmp_path,
        groups={"add-marker": {1: ("Drive the stack", "")}},
        e2e=(1,),
        checks=[(False, "STUB-OUTPUT-0"), (True, "")],
    )

    assert outcome.status == "open"
    assert [event for event in recorder.events if event in STEPS | {"claude:fix_stub"}] == [
        "claude:tests",
        "stub-checks",
        "claude:fix_stub",
        "stub-checks",
        "commit:test",
    ]
    assert "STUB-OUTPUT-0" in recorder.fix_prompts[0]
    assert subjects(repo) == ["test: Drive the stack"]
