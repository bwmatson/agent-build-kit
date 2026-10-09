"""A tier 1 command that does not finish fails tier 1 with where it was waiting
(spec: flaky-tests).

The commands are real child processes run by the default runner: a run whose tests
all pass and whose process then does not exit, because a thread nothing joins keeps it
alive. Each script bounds its own wait, so a runner without the limit ends the test by
the script exiting rather than by hanging the suite.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agent_build_kit.config import LimitsConfig
from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.conftest import make_installation

# Every test passed; a non-daemon thread then keeps the interpreter alive. SIGABRT makes
# the interpreter dump every thread's stack, which names `waiting_here`.
HANGS_AT_EXIT = """\
import faulthandler, threading

faulthandler.enable()


def waiting_here():
    threading.Event().wait(15)


print("12 tests passed", flush=True)
threading.Thread(target=waiting_here).start()
"""

# The same, but the process ignores the abort and has to be ended.
IGNORES_THE_ABORT = """\
import signal, threading

signal.signal(signal.SIGABRT, signal.SIG_IGN)
print("12 tests passed", flush=True)
threading.Event().wait(15)
"""

FINISHES = """\
import signal, sys

signal.signal(signal.SIGABRT, lambda *args: print("SIGNALLED"))
print("12 tests passed")
"""


class ScriptProfile(PythonUvProfile):
    """The python-uv profile running one script as its only check."""

    def __init__(self, script: str) -> None:
        self.script = script

    def lint_command(self, base: str) -> list[str]:
        return [sys.executable, "-c", "pass"]

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return [[sys.executable, "-c", self.script]]


def tier1(tmp_path: Path, script: str, **limits: float) -> tuple[bool, str]:
    make_installation(tmp_path / "planning", limits=limits)
    repo = tmp_path / "repo"
    repo.mkdir()
    return build_tier1(profile=ScriptProfile(script), changed=lambda *a: ["tests/test_x.py"])(
        cwd=repo, base="main"
    )


def test_the_limit_defaults_to_far_more_than_a_suite_takes() -> None:
    assert LimitsConfig().tier1_command_seconds >= 1800


def test_a_run_that_passes_and_does_not_exit_fails_naming_the_command_and_the_time(
    tmp_path: Path,
) -> None:
    passed, message = tier1(
        tmp_path, HANGS_AT_EXIT, tier1_command_seconds=3, tier1_abort_grace_seconds=5
    )

    assert not passed
    assert message.startswith(f"$ {sys.executable} -c"), "the command is named"
    assert "3 seconds" in message
    assert "12 tests passed" in message, "the end of its output is carried"
    assert "waiting_here" in message, "the stack dump shows where the threads were waiting"


def test_a_command_that_ignores_the_abort_is_ended_after_the_grace(tmp_path: Path) -> None:
    passed, message = tier1(
        tmp_path, IGNORES_THE_ABORT, tier1_command_seconds=2, tier1_abort_grace_seconds=1
    )

    assert not passed
    assert "2 seconds" in message
    assert "12 tests passed" in message


def test_a_command_that_finishes_in_time_is_not_signalled(tmp_path: Path) -> None:
    passed, message = tier1(
        tmp_path, FINISHES, tier1_command_seconds=60, tier1_abort_grace_seconds=1
    )

    assert passed, message
    assert "SIGNALLED" not in message
