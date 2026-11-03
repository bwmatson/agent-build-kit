"""A unit-test command that does not finish fails unit-test with where it was waiting
(spec: flaky-tests).

The commands are real child processes run by the default runner: a run whose tests
all pass and whose process then does not exit, because a thread nothing joins keeps it
alive. Each script bounds its own wait, so a runner without the limit ends the test by
the script exiting rather than by hanging the suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent_build_kit.config import LimitsConfig
from agent_build_kit.pipeline.wiring import build_unit_test
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
print("EXITED ON ITS " + "OWN", flush=True)
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

    def _commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str], **_workers: object
    ) -> list[list[str]]:
        return [[sys.executable, "-c", self.script]]

    # Assigned, not defined: a scan for changed tests takes any `def test_*` for one.
    test_commands = _commands


def unit_test(tmp_path: Path, script: str, **limits: float) -> tuple[bool, str]:
    make_installation(tmp_path / "planning", limits=limits)
    repo = tmp_path / "repo"
    repo.mkdir()
    return build_unit_test(profile=ScriptProfile(script), changed=lambda *a: ["tests/test_x.py"])(
        cwd=repo, base="main"
    )


def test_the_limit_defaults_to_far_more_than_a_suite_takes() -> None:
    assert LimitsConfig().unit_test_command_seconds >= 1800


def test_a_run_that_passes_and_does_not_exit_fails_naming_the_command_and_the_time(
    tmp_path: Path,
) -> None:
    passed, message = unit_test(
        tmp_path, HANGS_AT_EXIT, unit_test_command_seconds=3, unit_test_abort_grace_seconds=5
    )

    assert not passed
    assert message.startswith(f"$ {sys.executable} -c"), "the command is named"
    assert "3 seconds" in message
    assert "12 tests passed" in message, "the end of its output is carried"
    assert "waiting_here" in message, "the stack dump shows where the threads were waiting"


def test_a_command_that_ignores_the_abort_is_ended_after_the_grace(tmp_path: Path) -> None:
    passed, message = unit_test(
        tmp_path, IGNORES_THE_ABORT, unit_test_command_seconds=2, unit_test_abort_grace_seconds=1
    )

    assert not passed
    assert "2 seconds" in message
    assert "12 tests passed" in message
    assert "EXITED ON ITS OWN" not in message, "it was ended, not waited for"


def test_a_command_that_finishes_in_time_is_not_signalled(tmp_path: Path) -> None:
    passed, message = unit_test(
        tmp_path, FINISHES, unit_test_command_seconds=60, unit_test_abort_grace_seconds=1
    )

    assert passed, message
    assert "SIGNALLED" not in message


# The child the next script leaves in a session of its own: it holds the output pipes until the
# file named by argv[1] exists, the folder that holds the file is gone, or argv[2] seconds have
# passed. pytest removes a passed test's folder at teardown, before the child looks for the file
# again, so the folder going is how a passing run ends it; the deadline ends one that was killed.
DETACHED_CHILD = """\
import os, sys, threading, time

release, seconds = sys.argv[1], float(sys.argv[2])
folder = os.path.dirname(release)
deadline = time.monotonic() + seconds
while os.path.isdir(folder) and not os.path.exists(release) and time.monotonic() < deadline:
    threading.Event().wait(0.05)
"""

# The parent waits this long itself, and the child must outlast it and the test's assertions.
DETACHED_PARENT_SECONDS = 30
DETACHED_CHILD_SECONDS = 60

# The script ignores the abort, prints, and leaves the detached child holding the output pipes.
DETACHED_HOLDER = """\
import signal, subprocess, sys, threading

signal.signal(signal.SIGABRT, signal.SIG_IGN)
subprocess.Popen(
    [sys.executable, "-c", {child!r}, {release!r}, {seconds!r}], start_new_session=True
)
print("12 tests passed", flush=True)
threading.Event().wait({wait})
"""


def test_a_detached_descendant_holding_the_output_does_not_hold_unit_test(tmp_path: Path) -> None:
    release = tmp_path / "release"
    script = DETACHED_HOLDER.format(
        child=DETACHED_CHILD,
        release=str(release),
        seconds=str(DETACHED_CHILD_SECONDS),
        wait=DETACHED_PARENT_SECONDS,
    )
    try:
        passed, message = unit_test(
            tmp_path, script, unit_test_command_seconds=1, unit_test_abort_grace_seconds=1
        )
    finally:
        release.write_text("")

    assert not passed
    assert "1 seconds" in message
    assert "12 tests passed" in message


def run_detached_child(release: Path, seconds: float) -> int:
    """Run the detached child's script on its own, bounded so a child that never ends fails here."""
    ran = subprocess.run(
        [sys.executable, "-c", DETACHED_CHILD, str(release), str(seconds)], timeout=10, check=False
    )
    return ran.returncode


def test_the_detached_child_ends_at_its_deadline_when_nothing_releases_it(tmp_path: Path) -> None:
    assert run_detached_child(tmp_path / "never_written", 1) == 0


def test_the_detached_child_ends_at_once_when_it_is_released(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.write_text("")

    assert run_detached_child(release, DETACHED_CHILD_SECONDS) == 0, (
        "ended by the file, not the deadline"
    )


def test_the_detached_child_ends_at_once_when_its_folder_is_gone(tmp_path: Path) -> None:
    gone = tmp_path / "removed_with_the_test" / "release"

    assert run_detached_child(gone, DETACHED_CHILD_SECONDS) == 0, (
        "ended by the folder, not the deadline"
    )


def test_the_detached_child_outlives_the_test_that_starts_it() -> None:
    assert DETACHED_CHILD_SECONDS > DETACHED_PARENT_SECONDS
