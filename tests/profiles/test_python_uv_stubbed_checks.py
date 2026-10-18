"""python-uv reads a JUnit report of the red run in a stubbed mode (spec: test-stubs).

The reports have the shape pytest writes (`tests/fixtures/external/pytest/`): the failing
test's exception type leads the `message`, and the traceback line follows in the text.
"""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.red_check import REPORT_MARK
from agent_build_kit.profiles.python_uv import PROFILE

ERROR_NAMES = ("ModuleNotFoundError", "ImportError", "AttributeError")

SAID = {
    "ModuleNotFoundError": "ModuleNotFoundError: No module named 'nothing_here'",
    "ImportError": "ImportError: cannot import name 'thing' from 'pkg'",
    "AttributeError": "AttributeError: module 'pkg' has no attribute 'thing'",
    "AssertionError": "assert 1 == 2",
    "NotImplementedError": "NotImplementedError",
}


def failing(kind: str, name: str = "test_new") -> str:
    said = SAID[kind]
    return (
        f'<testcase classname="test_case" name="{name}">'
        f'<failure message="{said}">E   {said}</failure></testcase>'
    )


def passing(name: str = "test_ok") -> str:
    return f'<testcase classname="test_case" name="{name}"/>'


def run(*cases: str) -> str:
    report = (
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
        f'<testsuite name="pytest" tests="{len(cases)}">{"".join(cases)}</testsuite></testsuites>'
    )
    return f"1 failed in 0.05s\n{REPORT_MARK}\n{report}\n"


@pytest.mark.parametrize("kind", ERROR_NAMES)
def test_a_test_failing_with_a_missing_name_is_rejected_naming_it_only_when_stubbed(
    kind: str,
) -> None:
    output = run(failing(kind, "test_needs_stub"))

    ok, problems = PROFILE.interpret_red(output, 1, stubbed=True)

    assert not ok
    assert any("test_needs_stub" in problem for problem in problems), problems
    assert PROFILE.interpret_red(output, 1) == (True, [])


@pytest.mark.parametrize("kind", ["AssertionError", "NotImplementedError"])
def test_an_assertion_or_not_implemented_is_red_in_both_readings(kind: str) -> None:
    output = run(failing(kind))

    assert PROFILE.interpret_red(output, 1, stubbed=True) == (True, [])
    assert PROFILE.interpret_red(output, 1) == (True, [])


def test_a_passing_test_is_rejected_in_both_readings() -> None:
    output = run(failing("AssertionError"), passing())

    stubbed_ok, stubbed_problems = PROFILE.interpret_red(output, 1, stubbed=True)
    ok, problems = PROFILE.interpret_red(output, 1)

    assert not stubbed_ok
    assert stubbed_problems
    assert not ok
    assert problems
