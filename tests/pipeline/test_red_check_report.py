"""The red check reads pytest's JUnit report, not its console.

The fixtures under `tests/fixtures/external/pytest/` are the reports pytest
wrote for one failing test of each kind, with the version in the header; a
change in the report's shape fails here. The console matching in
`interpret_pytest` is only the fallback, and says so when it runs.
"""

import logging
from pathlib import Path

import pytest

from agent_build_kit.pipeline.red_check import REPORT_MARK, judge_red, red_check
from agent_build_kit.profiles.python_uv import PROFILE

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "external" / "pytest"


def recorded(name: str) -> str:
    return (FIXTURES / f"{name}.xml").read_text()


@pytest.mark.parametrize(
    ("name", "verdict", "test"),
    [
        ("missing_implementation", "accepted", "test_new"),
        ("import_error", "rejected", "test_case"),
        ("fixture_error", "rejected", "test_new"),
        ("assertion", "accepted", "test_new"),
    ],
)
def test_a_recorded_report_is_judged_by_its_failures(name: str, verdict: str, test: str) -> None:
    result = red_check(recorded(name))

    assert result.verdict == verdict
    assert any(test in named for named in result.tests)


@pytest.mark.parametrize("name", ["import_error", "fixture_error"])
def test_a_rejection_says_why(name: str) -> None:
    assert red_check(recorded(name)).problems


@pytest.mark.parametrize("name", ["missing_implementation", "assertion"])
def test_an_accepted_run_has_no_problems(name: str) -> None:
    assert red_check(recorded(name)).problems == ()


def test_a_report_with_no_failures_is_not_red() -> None:
    empty = '<?xml version="1.0"?><testsuites><testsuite tests="1" failures="0" errors="0">'
    empty += '<testcase classname="test_case" name="test_new"/></testsuite></testsuites>'

    result = red_check(empty)

    assert result.verdict == "rejected"
    assert result.problems


def test_the_report_decides_over_the_console(caplog: pytest.LogCaptureFixture) -> None:
    """A console that reads as accepted does not outvote a report that rejects."""
    console = "E   AssertionError\nFAILED test_case.py::test_new\n1 failed in 0.01s\n"

    with caplog.at_level(logging.WARNING):
        result = judge_red(recorded("fixture_error"), console, exit_code=1)

    assert result.verdict == "rejected"
    assert "fallback" not in caplog.text.lower()


def test_a_report_that_could_not_be_written_falls_back_to_the_console_and_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    console = "E   AssertionError\nFAILED test_case.py::test_new\n1 failed in 0.01s\n"

    with caplog.at_level(logging.WARNING):
        result = judge_red(None, console, exit_code=1)

    assert result.verdict == "accepted"
    assert "fallback" in caplog.text.lower()


@pytest.mark.parametrize("report", [None, "", "not xml at all"])
def test_an_unreadable_report_is_a_missing_one(
    report: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    console = "1 passed in 0.01s\n"

    with caplog.at_level(logging.WARNING):
        result = judge_red(report, console, exit_code=0)

    assert result.verdict == "rejected"
    assert "fallback" in caplog.text.lower()


def test_the_python_profile_asks_pytest_for_the_report() -> None:
    command = PROFILE.red_command(["tests/test_thing.py"])

    assert "--junitxml=" in command
    assert "tests/test_thing.py" in command


STDERR_NOTICE = (
    "warning: `VIRTUAL_ENV=/x/.venv` does not match the project environment path `.venv` "
    "and will be ignored\n"
)


def test_stderr_after_the_report_does_not_hide_it(caplog: pytest.LogCaptureFixture) -> None:
    """The gate hands the profile stdout + stderr, so a `uv run` notice lands after the XML."""
    console = "E   AssertionError\nFAILED test_case.py::test_new\n1 failed in 0.01s\n"
    output = f"{console}{REPORT_MARK}\n{recorded('fixture_error')}\n{STDERR_NOTICE}"

    with caplog.at_level(logging.WARNING):
        ok, problems = PROFILE.interpret_red(output, 1)

    assert not ok
    assert any("test_new" in problem for problem in problems)
    assert "fallback" not in caplog.text.lower()


def test_a_fixture_that_raises_not_implemented_at_setup_is_red() -> None:
    report = (
        '<testsuites><testsuite tests="1" errors="1"><testcase classname="t" name="test_new">'
        '<error message="failed on setup with &quot;NotImplementedError&quot;">'
        "t.py:3: NotImplementedError</error></testcase></testsuite></testsuites>"
    )

    assert red_check(report).verdict == "accepted"
