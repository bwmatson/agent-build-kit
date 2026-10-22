"""The verified list is composed from the unit's recorded results, never from the reviewer."""

from __future__ import annotations

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.pr_body import build_pr_body, verified_list
from agent_build_kit.pipeline.unit_store import Description, E2eState
from agent_build_kit.pipeline.verdict import GateResult, VerdictFacts
from tests.factories import stored_unit as unit


def facts(**overrides) -> VerdictFacts:
    return VerdictFacts(**{"kind": TestTier.UNIT_TEST, **overrides})


def line_with(text: str, word: str) -> str:
    return next(line for line in text.splitlines() if word in line)


def test_every_recorded_result_is_listed() -> None:
    text = verified_list(facts(red_first=GateResult.PASSED, unit_test=GateResult.PASSED), rounds=2)

    assert "seen to fail first" in text
    assert "passed" in line_with(text, "unit-test")
    assert "2 review rounds" in text
    assert "not recorded" not in text


def test_an_e2e_unit_lists_its_e2e_result() -> None:
    text = verified_list(
        facts(
            kind=TestTier.E2E_TEST,
            red_first=GateResult.PASSED,
            unit_test=GateResult.PASSED,
            e2e_state=E2eState.PASSED,
        ),
        rounds=1,
    )

    assert "passed" in line_with(text, "e2e-test")


def test_a_result_that_is_not_recorded_is_listed_as_such() -> None:
    text = verified_list(facts(kind=TestTier.E2E_TEST, red_first=GateResult.PASSED), rounds=None)

    assert "not recorded" in line_with(text, "e2e-test")
    assert "not recorded" in line_with(text, "unit-test")
    assert "not recorded" in line_with(text, "review")


def test_a_unit_that_is_not_e2e_does_not_list_an_e2e_result() -> None:
    assert "e2e-test result" not in verified_list(facts(), rounds=1)


def test_the_reviewer_claiming_a_pass_changes_nothing() -> None:
    claim = Description(summary="All the tests passed.", changes=("The unit tests passed.",))
    u = unit(description=claim)

    body = build_pr_body(u, graph=[u], base="main", facts=facts(), rounds=1)

    start = body[body.index("## Start here") :]
    assert "not recorded" in line_with(start, "unit-test")
    assert "passed" not in line_with(start, "unit-test")


def test_the_same_results_give_the_same_text() -> None:
    recorded = facts(red_first=GateResult.PASSED, unit_test=GateResult.PASSED)

    assert verified_list(recorded, rounds=3) == verified_list(recorded, rounds=3)
    assert verified_list(recorded, rounds=3) != verified_list(recorded, rounds=1)


def test_a_recorded_failed_red_run_is_listed_as_failed_not_as_not_recorded() -> None:
    text = verified_list(facts(red_first=GateResult.FAILED), rounds=1)

    line = line_with(text, "failing run")
    assert "failed" in line
    assert "not recorded" not in line
