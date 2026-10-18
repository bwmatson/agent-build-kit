"""The red reading in a stubbed build: import, module and attribute errors are not red
(spec: test-stubs), by the console fallback and by the JUnit report."""

from __future__ import annotations

from agent_build_kit.pipeline.red_check import (
    REPORT_MARK,
    interpret_pytest,
    judge_red,
    split_report,
)

ATTRIBUTE_ONLY = """\
tests/test_thing.py:4: AttributeError
=========================== short test summary info ============================
FAILED tests/test_thing.py::test_x - AttributeError: module 'src' has no attribute 'x'
1 failed in 0.05s
"""

IMPORT_ONLY = """\
ImportError while importing test module '/repo/tests/test_thing.py'.
E   ModuleNotFoundError: No module named 'src.thing'
=========================== short test summary info ============================
ERROR tests/test_thing.py
1 error in 0.04s
"""

ASSERTION_AND_ATTRIBUTE = """\
tests/test_thing.py:4: AssertionError
=========================== short test summary info ============================
FAILED tests/test_thing.py::test_x - assert 0 == 1
FAILED tests/test_thing.py::test_y - AttributeError: no attribute 'y'
2 failed in 0.05s
"""

REPORT = (
    '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
    '<testsuite name="pytest" tests="2">'
    '<testcase classname="test_case" name="test_a"><failure message="assert 1 == 2">'
    "E   assert 1 == 2</failure></testcase>"
    '<testcase classname="test_case" name="test_b">'
    "<failure message=\"AttributeError: no attribute 'b'\">"
    "E   AttributeError: no attribute 'b'</failure></testcase>"
    "</testsuite></testsuites>"
)


def test_the_console_fallback_rejects_output_whose_only_markers_are_missing_names() -> None:
    for output, marker in ((ATTRIBUTE_ONLY, "AttributeError"), (IMPORT_ONLY, "ImportError")):
        ok, problems = interpret_pytest(output, exit_code=1, stubbed=True)

        assert not ok
        assert any(marker in problem for problem in problems), problems
        assert interpret_pytest(output, exit_code=1)[0]


def test_the_console_fallback_accepts_an_assertion_failure_when_stubbed() -> None:
    ok, problems = interpret_pytest(ASSERTION_AND_ATTRIBUTE, exit_code=1, stubbed=True)

    assert ok, problems


def test_with_a_report_the_exception_type_of_each_failing_test_decides() -> None:
    report, console = split_report(f"{ASSERTION_AND_ATTRIBUTE}{REPORT_MARK}\n{REPORT}\n")

    stubbed = judge_red(report, console, 1, stubbed=True)
    plain = judge_red(report, console, 1)

    assert stubbed.verdict == "rejected"
    assert any("test_b" in problem for problem in stubbed.problems)
    assert not any("test_a" in problem for problem in stubbed.problems)
    assert plain.verdict == "accepted"
