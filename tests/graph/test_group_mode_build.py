"""The graph builds each group by its stored mode: a `no_code` or `refactor` group goes straight
to `implement` with no tests step, no static checks of stubs and an implementation prompt that
does not ask for the previous commit's tests to pass, a unit mixing modes is built group by group,
and a named step for a later red check sits between `stub_checks` and `implement` (spec:
group-build-modes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.graph.nodes import ROUTES
from agent_build_kit.graph.state import Node
from tests.graph.branch_fakes import agent_calls, built, subjects, titled

PREVIOUS_TESTS = "Make the tests written in the previous commit pass"


def key(number: int) -> str:
    return f"add-marker/{number}"


@pytest.mark.parametrize("mode", ["no_code", "refactor"])
def test_a_group_with_no_tests_step_goes_straight_to_implement(tmp_path: Path, mode: str) -> None:
    recorder, outcome, repo = built(
        tmp_path, groups={"add-marker": titled(1)}, modes={key(1): mode}
    )

    assert outcome.status == "open"
    assert agent_calls(recorder.events) == ["claude:impl"]
    assert "stub-checks" not in recorder.events
    assert subjects(repo) == ["feat: G1"]
    assert "review" in recorder.events


@pytest.mark.parametrize("mode", ["no_code", "refactor"])
def test_the_implementation_prompt_of_such_a_group_does_not_ask_for_tests_to_pass(
    tmp_path: Path, mode: str
) -> None:
    recorder, _, _ = built(tmp_path, groups={"add-marker": titled(1)}, modes={key(1): mode})

    implementation = next(p for p in recorder.prompts if "task group(s) 1" in p)
    assert PREVIOUS_TESTS not in implementation


def test_a_unit_that_mixes_modes_is_built_group_by_group(tmp_path: Path) -> None:
    recorder, outcome, repo = built(
        tmp_path,
        groups={"add-marker": titled(1, 2, 3)},
        modes={key(1): "tests_and_code", key(2): "no_code", key(3): "tests_and_code"},
    )

    assert outcome.status == "open"
    assert agent_calls(recorder.events) == [
        "claude:tests",
        "claude:impl",
        "claude:impl",
        "claude:tests",
        "claude:impl",
    ]
    assert subjects(repo) == ["test: G1", "feat: G1", "feat: G2", "test: G3", "feat: G3"]


def test_a_lone_feat_of_a_no_code_group_on_the_branch_is_a_built_group(tmp_path: Path) -> None:
    recorder, outcome, repo = built(
        tmp_path,
        groups={"add-marker": titled(3, 4)},
        seeded=["test: G3", "feat: G3", "feat: G4"],
        modes={key(4): "no_code"},
    )

    assert outcome.status == "open"
    assert agent_calls(recorder.events) == []
    assert subjects(repo) == ["test: G3", "feat: G3", "feat: G4"]


def test_a_named_step_sits_between_stub_checks_and_implement() -> None:
    later_check = Node("red_check")

    assert later_check in ROUTES[Node.STUB_CHECKS][1]
    assert Node.IMPLEMENT in ROUTES[later_check][1]
