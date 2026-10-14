"""A unit's tier 2 output keeps the failed tests and why they failed.

The output is one section per command, a failed command weighing more than a
passing one. Within a failed command, the identifier and the error lines of each
failed test come before the remainder; a profile that cannot read the failed
tests keeps the tail of the command's output. The command runner is the faked
boundary: it returns pytest's console text.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.wiring import Tier2Session
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.factories import unit
from tests.tier2_failure_fakes import checkout

FAILED = 7
BUDGET = 4_000
NAMES = [f"test_route_{n}" for n in range(FAILED)]
IDS = [f"tests/live/test_route.py::{name}" for name in NAMES]
CLOSING = f"========================= {FAILED} failed, 3 passed in 4.21s ========================="
ERRORS = [f"E   AssertionError: route {n} answered 404" for n in range(FAILED)]


def failing_log(*, head: str = "") -> str:
    """A failed pytest run over seven tests: long tracebacks, a coverage table between the
    failures and the closing line, so that the last four thousand characters hold none of
    the failed tests."""
    blocks = [
        f"{'_' * 20} {name} {'_' * 20}\n"
        + "".join(
            f"tests/live/test_route.py:{line}: in helper\n    call({line})\n" for line in range(12)
        )
        + f"{error}\n"
        for name, error in zip(NAMES, ERRORS, strict=True)
    ]
    summary = "".join(f"FAILED {id_} - AssertionError\n" for id_ in IDS)
    coverage = "".join(f"src/pkg/module_{n:03d}.py   120   4   97%\n" for n in range(120))
    return (
        f"{head}"
        "============================= test session starts ==============================\n"
        "=================================== FAILURES ===================================\n"
        + "".join(blocks)
        + "=========================== short test summary info ============================\n"
        + summary
        + coverage
        + f"{CLOSING}\n"
    )


def passing_log() -> str:
    lines = "".join(f"tests/live/test_ok.py::test_ok_{n} PASSED\n" for n in range(300))
    return f"{lines}======================= 300 passed in 9.10s =======================\n"


class Blind(PythonUvProfile):
    """A profile that cannot say which tests failed: it has no reading of them."""

    def __getattribute__(self, name: str) -> Any:
        if name in ("failed_tests", "failure_sections"):
            raise AttributeError(name)
        return super().__getattribute__(name)


def runner(answers: dict[str, tuple[int, str]]):
    """A runner answering by the directory it runs in: the last path part, `.` for the root."""

    def run(command: list[str], *, cwd: Path, **kwargs: Any) -> subprocess.CompletedProcess:
        code, out = answers[cwd.name if cwd.name in answers else "checkout"]
        return subprocess.CompletedProcess(command, code, out, "")

    return run


def session(tmp_path: Path, run, **kwargs: Any) -> Tier2Session:
    return Tier2Session(
        unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        timeout=5,
        run=run,
        sha=lambda cwd: "abc1234",
        **kwargs,
    )


def test_seven_failed_tests_in_a_long_log_are_all_named_with_their_error_lines(
    tmp_path: Path,
) -> None:
    root = checkout(tmp_path)
    log = failing_log()
    assert len(log) > BUDGET
    gate = session(tmp_path, runner({"checkout": (1, log)}))

    gate.run(cwd=root)

    assert gate.result is not None
    for id_, error in zip(IDS, ERRORS, strict=True):
        assert id_ in gate.result.output
        assert error in gate.result.output


def test_a_passing_command_does_not_push_a_failed_ones_tests_out(tmp_path: Path) -> None:
    root = checkout(tmp_path, "api", "web")
    gate = session(
        tmp_path,
        runner({"api": (0, passing_log()), "web": (1, failing_log())}),
        projects=[ProjectConfig(path="api"), ProjectConfig(path="web")],
    )

    gate.run(cwd=root)

    assert gate.result is not None
    for id_, error in zip(IDS, ERRORS, strict=True):
        assert id_ in gate.result.output
        assert error in gate.result.output
    assert "(in api)" in gate.result.output, "a passing command keeps a section of its own"
    assert "(in web)" in gate.result.output


def test_a_profile_that_cannot_read_the_failed_tests_keeps_the_tail(tmp_path: Path) -> None:
    root = checkout(tmp_path)
    log = failing_log(head="HEAD-OF-THE-LOG\n")
    gate = session(tmp_path, runner({"checkout": (1, log)}), profile=Blind())

    gate.run(cwd=root)

    assert gate.result is not None
    output = gate.result.output
    assert output.startswith("$ "), "the section still says which command it was"
    assert output.rstrip().endswith(CLOSING)
    assert "HEAD-OF-THE-LOG" not in output
    assert IDS[0] not in output
