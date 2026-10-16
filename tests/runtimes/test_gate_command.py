"""A gate command answers by its exit status and the first line it prints."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit.runtimes.providers import GateCommandResult, run_gate_command
from tests.redaction_fakes import SECRET, known

ARGV = ["probe", "--quota"]


class FakeRun:
    """A `Run` that records how it was called and answers with a fixed result or error."""

    def __init__(self, *, code: int = 0, stdout: str = "", error: Exception | None = None) -> None:
        self.code = code
        self.stdout = stdout
        self.error = error
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args, **kwargs) -> subprocess.CompletedProcess:  # noqa: ANN002, ANN003
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(args[0], self.code, stdout=self.stdout, stderr="noise")


def result_of(run: FakeRun, tmp_path: Path, timeout: float = 30) -> GateCommandResult:
    return run_gate_command(ARGV, root=tmp_path, timeout_seconds=timeout, run=run)


def test_exit_zero_is_usable(tmp_path: Path) -> None:
    result = result_of(FakeRun(code=0, stdout="all fine\n"), tmp_path)

    assert result.state == "usable"


def test_a_failing_exit_is_held_with_the_first_line_as_the_reason(tmp_path: Path) -> None:
    result = result_of(FakeRun(code=3, stdout="quota spent\n"), tmp_path)

    assert (result.state, result.reason) == ("held", "quota spent")


def test_a_failing_exit_that_prints_nothing_says_the_status(tmp_path: Path) -> None:
    result = result_of(FakeRun(code=1, stdout=""), tmp_path)

    assert (result.state, result.reason) == ("held", "gate command exited 1")


def test_a_first_line_of_three_hundred_characters_is_cut_at_two_hundred(tmp_path: Path) -> None:
    result = result_of(FakeRun(code=2, stdout="x" * 300 + "\n"), tmp_path)

    assert result.reason == "x" * 200


def test_the_line_is_trimmed_and_later_lines_are_ignored(tmp_path: Path) -> None:
    result = result_of(FakeRun(code=2, stdout="  over the limit  \nsecond line\nthird\n"), tmp_path)

    assert result.reason == "over the limit"


def test_a_configured_secret_in_the_line_is_redacted(tmp_path: Path) -> None:
    with known():
        result = result_of(FakeRun(code=2, stdout=f"key {SECRET} is spent\n"), tmp_path)

    assert result.state == "held"
    assert SECRET not in result.reason
    assert "is spent" in result.reason


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("probe"),
        PermissionError("probe"),
        subprocess.TimeoutExpired(ARGV, 1),
    ],
)
def test_a_command_that_cannot_start_or_runs_too_long_is_unknown(
    error: Exception, tmp_path: Path
) -> None:
    result = result_of(FakeRun(error=error), tmp_path)

    assert result.state == "unknown"
    assert result.reason


def test_the_argv_runs_from_the_root_without_a_shell_and_with_stdin_closed(tmp_path: Path) -> None:
    run = FakeRun(code=0)

    result_of(run, tmp_path, timeout=7)

    ((args, kwargs),) = run.calls
    assert list(args[0]) == ARGV
    assert not kwargs.get("shell")
    assert kwargs["cwd"] == tmp_path
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["timeout"] == 7


def test_a_command_that_does_not_exist_is_unknown_through_the_real_runner(tmp_path: Path) -> None:
    result = run_gate_command(
        ["abk-no-such-program-for-the-gate"], root=tmp_path, timeout_seconds=5
    )

    assert result.state == "unknown"


def test_a_command_that_sleeps_past_the_timeout_is_killed_and_unknown(tmp_path: Path) -> None:
    marker = tmp_path / "finished"
    script = f"import time, pathlib; time.sleep(30); pathlib.Path({str(marker)!r}).touch()"

    result = run_gate_command([sys.executable, "-c", script], root=tmp_path, timeout_seconds=0.5)

    assert result.state == "unknown"
    assert not marker.exists()
