"""python-uv reads a JUnit report of the red run in a stubbed mode (spec: test-stubs).

A test failing in its body with a missing attribute, module or name is read from the
reports pytest wrote (`tests/fixtures/external/pytest/`); the passing test is built by hand
in the same shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.red_check import REPORT_MARK
from agent_build_kit.profiles.python_uv import PROFILE

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "external" / "pytest"


def recorded(name: str) -> str:
    """The console and the recorded report of `name`, as the red command prints them."""
    return f"1 failed in 0.05s\n{REPORT_MARK}\n{(FIXTURES / f'{name}.xml').read_text()}\n"


PASSING = (
    '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
    '<testsuite name="pytest" tests="2">'
    '<testcase classname="test_case" name="test_new"><failure message="assert 1 == 2">'
    "E   assert 1 == 2</failure></testcase>"
    '<testcase classname="test_case" name="test_ok"/></testsuite></testsuites>'
)


@pytest.mark.parametrize(
    "name", ["missing_attribute", "missing_module_in_body", "missing_name_in_body"]
)
def test_a_test_failing_with_a_missing_name_is_rejected_naming_it_only_when_stubbed(
    name: str,
) -> None:
    output = recorded(name)

    ok, problems = PROFILE.interpret_red(output, 1, stubbed=True)

    assert not ok
    assert any("test_new" in problem and "stub" in problem for problem in problems), problems
    assert PROFILE.interpret_red(output, 1) == (True, [])


@pytest.mark.parametrize("name", ["assertion", "missing_implementation"])
def test_an_assertion_or_not_implemented_is_red_in_both_readings(name: str) -> None:
    output = recorded(name)

    assert PROFILE.interpret_red(output, 1, stubbed=True) == (True, [])
    assert PROFILE.interpret_red(output, 1) == (True, [])


def test_a_passing_test_is_rejected_in_both_readings() -> None:
    output = f"1 failed, 1 passed in 0.05s\n{REPORT_MARK}\n{PASSING}\n"

    stubbed_ok, stubbed_problems = PROFILE.interpret_red(output, 1, stubbed=True)
    ok, problems = PROFILE.interpret_red(output, 1)

    assert not stubbed_ok
    assert stubbed_problems
    assert not ok
    assert problems
