"""The helper that makes a missing OpenSpec CLI one failure with one message."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.openspec_cli import probe, require

MESSAGE = "the OpenSpec CLI is not installed"
STDERR = "\n".join(f"line {n}" for n in range(1, 9))


def completed(status: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["openspec"], status, stdout="", stderr=stderr)


class FakeRunner:
    def __init__(self, status: int = 0, *, stderr: str = "", raises: Exception | None = None):
        self.status, self.stderr, self.raises = status, stderr, raises
        self.argv: list[list[str]] = []
        self.cwd_existed: list[bool] = []

    def __call__(self, argv, **kwargs):
        self.argv.append(list(argv))
        self.cwd_existed.append(Path(kwargs["cwd"]).is_dir())
        if self.raises:
            raise self.raises
        return completed(self.status, self.stderr)


def test_probe_returns_on_status_zero_and_asks_for_the_version_in_a_directory() -> None:
    runner = FakeRunner(0)

    probe(runner)

    assert len(runner.argv) == 1
    assert runner.argv[0][-1] == "--version"
    assert runner.cwd_existed == [True]


@pytest.mark.parametrize("status", [127, 1])
def test_probe_fails_with_the_status_and_the_last_five_lines_of_stderr(status: int) -> None:
    with pytest.raises(pytest.fail.Exception) as raised:
        probe(FakeRunner(status, stderr=STDERR))

    text = str(raised.value)
    assert text.startswith(MESSAGE)
    assert str(status) in text
    assert all(f"line {n}" in text for n in range(4, 9))
    assert "line 3" not in text


def test_probe_fails_with_the_same_message_when_the_fetch_stalls() -> None:
    with pytest.raises(pytest.fail.Exception) as raised:
        probe(FakeRunner(raises=subprocess.TimeoutExpired(["npx"], 45)))

    assert str(raised.value).startswith(MESSAGE)
    assert "timeout" in str(raised.value)


def test_probe_fails_with_the_same_message_when_the_program_cannot_start() -> None:
    with pytest.raises(pytest.fail.Exception) as raised:
        probe(FakeRunner(raises=FileNotFoundError(2, "No such file or directory: 'npx'")))

    assert str(raised.value).startswith(MESSAGE)
    assert "npx" in str(raised.value)


@pytest.mark.parametrize("status", [0, 1])
def test_require_returns_a_result_with_status_zero_or_one_unchanged(status: int) -> None:
    result = completed(status)

    assert require(result) is result


def test_require_fails_a_result_with_status_127_with_the_same_message() -> None:
    with pytest.raises(pytest.fail.Exception) as raised:
        require(completed(127, "sh: 1: openspec: not found"))

    text = str(raised.value)
    assert text.startswith(MESSAGE)
    assert "127" in text
    assert "openspec: not found" in text


FIXTURE_CONFTEST = """
import subprocess
from pathlib import Path

import pytest

from tests.openspec_cli import probe

CALLS = Path(__file__).parent / "calls"
STATUS = __STATUS__


def runner(argv, **kwargs):
    with CALLS.open("a") as handle:
        handle.write("call\\n")
    return subprocess.CompletedProcess(argv, STATUS, stdout="", stderr="sh: 1: openspec: not found")


@pytest.fixture(scope="session")
def openspec_cli():
    probe(runner)
"""

TESTS = """
import pytest

pytestmark = pytest.mark.usefixtures("openspec_cli")


def test_one():
    pass


def test_two():
    pass
"""


def conftest_with(status: int) -> str:
    return FIXTURE_CONFTEST.replace("__STATUS__", str(status))


def test_a_session_that_asks_for_the_fixture_twice_runs_the_probe_once(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(conftest_with(0))
    pytester.makepyfile(test_users=TESTS)

    result = pytester.runpytest_inprocess("-p", "no:cacheprovider")

    result.assert_outcomes(passed=2)
    assert (pytester.path / "calls").read_text().count("call") == 1


def test_two_tests_fail_with_one_message_and_a_test_without_the_fixture_passes(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(conftest_with(127))
    pytester.makepyfile(test_users=TESTS, test_bystander="def test_other():\n    pass\n")

    result = pytester.runpytest_inprocess("-p", "no:cacheprovider")

    result.assert_outcomes(passed=1, errors=2)
    first_lines = [line for line in result.outlines if line.startswith(MESSAGE)]
    assert first_lines == [first_lines[0]] * 2
