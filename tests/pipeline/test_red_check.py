"""Did the tests commit actually fail, and fail honestly?

Committing tests first only proves something if they were run there and lost.
A test that passed before its implementation existed is testing nothing; a
test that failed because a fixture was broken or the file didn't parse is
failing for a reason unrelated to the behaviour it claims to cover.

So "red" is not simply a non-zero exit code. These tests pin which failures
count (docs/architecture.md).
"""

import pytest

from agent_build_kit.pipeline.red_check import (
    Rule,
    interpret_pytest,
    red_check,
)
from tests.junit_cases import failing, junit_report, passing

FAILED_ASSERTION = """\
tests/test_thing.py:4: AssertionError
=========================== short test summary info ============================
FAILED tests/test_thing.py::test_x - assert 0 == 1
1 failed in 0.05s
"""

NOT_IMPLEMENTED = """\
tests/test_thing.py:4: NotImplementedError
=========================== short test summary info ============================
FAILED tests/test_thing.py::test_x - NotImplementedError
1 failed in 0.05s
"""

MISSING_MODULE = """\
ImportError while importing test module '/repo/tests/test_thing.py'.
E   ModuleNotFoundError: No module named 'src.thing'
=========================== short test summary info ============================
ERROR tests/test_thing.py
1 error in 0.04s
"""

SOME_PASSED = """\
=========================== short test summary info ============================
FAILED tests/test_thing.py::test_x - assert 0 == 1
1 failed, 2 passed in 0.06s
"""

SYNTAX_ERROR = """\
E     File "/repo/tests/test_thing.py", line 3
E       def test_x(:
E                  ^
E   SyntaxError: invalid syntax
=========================== short test summary info ============================
ERROR tests/test_thing.py
1 error in 0.03s
"""

FIXTURE_MISSING = """\
file /repo/tests/test_thing.py, line 3
E       fixture 'db' not found
=========================== short test summary info ============================
ERROR tests/test_thing.py::test_x
1 error in 0.03s
"""

ALL_PASSED = """\
3 passed in 0.10s
"""


def test_an_assertion_failure_is_red() -> None:
    ok, problems = interpret_pytest(FAILED_ASSERTION, exit_code=1)

    assert ok
    assert problems == []


def test_not_implemented_is_red() -> None:
    """The expected failure when the tests commit carries stubs."""
    ok, _ = interpret_pytest(NOT_IMPLEMENTED, exit_code=1)

    assert ok


def test_a_missing_module_is_red() -> None:
    """The expected failure when the tests commit carries no stubs: the module
    arrives with the implementation, one commit later."""
    ok, _ = interpret_pytest(MISSING_MODULE, exit_code=2)

    assert ok


def test_a_passing_test_is_not_red() -> None:
    """The failure this check exists for: a test that passed before the
    implementation existed proves nothing about it."""
    ok, problems = interpret_pytest(SOME_PASSED, exit_code=1)

    assert not ok
    assert any("passed" in problem for problem in problems)


def test_everything_passing_is_not_red() -> None:
    ok, problems = interpret_pytest(ALL_PASSED, exit_code=0)

    assert not ok
    assert problems


def test_a_syntax_error_is_not_an_honest_failure() -> None:
    """It fails, but not because the behaviour is missing — and it would keep
    failing after the implementation landed."""
    ok, problems = interpret_pytest(SYNTAX_ERROR, exit_code=2)

    assert not ok
    assert any("SyntaxError" in problem for problem in problems)


def test_a_broken_fixture_is_not_an_honest_failure() -> None:
    ok, problems = interpret_pytest(FIXTURE_MISSING, exit_code=2)

    assert not ok
    assert any("fixture" in problem for problem in problems)


def test_no_tests_collected_is_not_red() -> None:
    """An empty run is the quietest way to fake a red: nothing ran, nothing
    passed, exit code non-zero."""
    ok, problems = interpret_pytest("no tests ran in 0.01s\n", exit_code=5)

    assert not ok
    assert any("no tests" in problem.lower() for problem in problems)


def test_unrecognized_output_is_not_red() -> None:
    """If we can't tell what happened, we don't certify it — same rule as the
    usage guard and the stub parser."""
    ok, problems = interpret_pytest("segmentation fault\n", exit_code=139)

    assert not ok
    assert problems


FILE = "tests/test_thing.py"
MODULE = "tests.test_thing"
MAY_PASS = [Rule.CHANGED, Rule.RENAMED, Rule.WITH_FILE]
MUST_FAIL = [Rule.NEW, Rule.ASSERTION_CHANGED]
ANOTHER_FAILS = failing(MODULE, "test_fails")
ANOTHER_RULE = {f"{FILE}::test_fails": Rule.NEW}


@pytest.mark.parametrize("rule", MAY_PASS)
def test_a_passing_case_of_a_test_that_may_pass_is_no_problem(rule: Rule) -> None:
    report = junit_report([passing(MODULE, "test_x"), ANOTHER_FAILS])

    result = red_check(report, rules={f"{FILE}::test_x": rule, **ANOTHER_RULE})

    assert result.problems == ()
    assert result.verdict == "accepted"


@pytest.mark.parametrize(
    ("classname", "name", "test_id"),
    [
        pytest.param(MODULE, "test_x", f"{FILE}::test_x", id="a function"),
        pytest.param(f"{MODULE}.TestGroup", "test_x", f"{FILE}::TestGroup::test_x", id="a method"),
        pytest.param(MODULE, "test_x[a-1]", f"{FILE}::test_x", id="a parametrized case"),
    ],
)
@pytest.mark.parametrize("rule", MUST_FAIL)
def test_a_passing_case_of_a_test_that_must_fail_is_a_problem_naming_the_test_and_its_rule(
    rule: Rule, classname: str, name: str, test_id: str
) -> None:
    report = junit_report([passing(classname, name), ANOTHER_FAILS])

    result = red_check(report, rules={test_id: rule, **ANOTHER_RULE})

    assert result.verdict == "rejected"
    assert any(f"{test_id}: {rule.value}: must fail" in problem for problem in result.problems)


def test_rules_that_match_no_case_of_the_report_are_warned_of(
    caplog: pytest.LogCaptureFixture,
) -> None:
    report = junit_report([passing("project.tests.test_thing", "test_x"), ANOTHER_FAILS])

    with caplog.at_level("WARNING"):
        red_check(report, rules={f"{FILE}::test_x": Rule.CHANGED})

    assert "none of the 1 rules given matched" in caplog.text


def test_rules_that_match_a_case_of_the_report_are_not_warned_of(
    caplog: pytest.LogCaptureFixture,
) -> None:
    report = junit_report([passing(MODULE, "test_x"), ANOTHER_FAILS])

    with caplog.at_level("WARNING"):
        red_check(report, rules={f"{FILE}::test_x": Rule.CHANGED, **ANOTHER_RULE})

    assert "matched" not in caplog.text


def test_a_test_that_must_fail_meets_its_rule_when_one_of_its_cases_failed() -> None:
    report = junit_report(
        [passing(MODULE, "test_p[1]"), passing(MODULE, "test_p[2]"), failing(MODULE, "test_p[-3]")]
    )

    result = red_check(report, rules={f"{FILE}::test_p": Rule.ASSERTION_CHANGED})

    assert result.problems == ()
    assert result.verdict == "accepted"


def test_a_test_that_must_fail_does_not_meet_its_rule_when_all_its_cases_passed() -> None:
    report = junit_report(
        [passing(MODULE, "test_p[1]"), passing(MODULE, "test_p[2]"), ANOTHER_FAILS]
    )

    result = red_check(report, rules={f"{FILE}::test_p": Rule.ASSERTION_CHANGED, **ANOTHER_RULE})

    assert any(
        f"{FILE}::test_p: {Rule.ASSERTION_CHANGED.value}: must fail" in problem
        for problem in result.problems
    )
