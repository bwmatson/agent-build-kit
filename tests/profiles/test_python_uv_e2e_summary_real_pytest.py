"""What the pinned pytest prints under the e2e-test flags, read by the profile's parser.

Below `-vv` pytest cuts each summary message to the terminal width and drops it when the
test id fills the line, so the flags and the parser are checked together against a real
run, on a narrow terminal and off CI, where the cut applies.
"""

import pytest

from agent_build_kit.profiles.python_uv import PROFILE

MESSAGE = "the first line of an exception message that runs well past eighty characters"
FIXTURE_MESSAGE = "[Errno 2] a module fixture could not find what it needs, and says so at length"
LONG_ID = "test_the_unit_is_built_reviewed_and_pushed_through_the_runtime_and_the_report_is_made"

TESTS = f'''\
import pytest

pytestmark = pytest.mark.local_stack


@pytest.fixture(scope="module")
def built():
    raise FileNotFoundError("{FIXTURE_MESSAGE}")


def test_short(built):
    pass


def {LONG_ID}():
    raise RuntimeError("{MESSAGE}\\nand a second line")


def test_message():
    raise RuntimeError("{MESSAGE}")
'''


def test_a_real_run_at_the_e2e_flags_keeps_the_whole_first_line_of_every_message(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("COLUMNS", "80")
    pytester.makeini("[pytest]\nmarkers =\n    local_stack: needs the live stack\n")
    pytester.makepyfile(test_live=TESTS)
    (command,) = PROFILE.e2e_commands(pytester.path, marker="local_stack")

    result = pytester.runpytest_subprocess(*command[command.index("pytest") + 1 :])

    failures = PROFILE.parse_test_failures(result.stdout.str())
    assert {failure.test.rpartition("::")[2]: failure.line for failure in failures} == {
        "test_short": f"FileNotFoundError: {FIXTURE_MESSAGE}",
        LONG_ID: f"RuntimeError: {MESSAGE}",
        "test_message": f"RuntimeError: {MESSAGE}",
    }
    assert len(failures) == 3
