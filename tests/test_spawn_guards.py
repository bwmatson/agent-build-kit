"""The suite's guards against a real agent process let an e2e test through
(spec: test-determinism).

A test marked `local_stack` — on the test, its class or its module — may start the
runtime's real spawn and a program named `claude`; every other test is refused, and the
guards on the login refresh, the usage window, `gh` and the code host hold for both. The
guards are driven in a child pytest whose conftest imports the real fixtures.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

CONFTEST = """\
from tests.conftest import (
    no_direct_claude,
    no_real_agent,
    no_real_gh,
    no_real_github,
    no_real_login_refresh,
    no_real_usage_reading,
)
"""

INI = """\
[pytest]
markers =
    local_stack: an e2e test
"""

# `original_spawn` is bound at import, before the autouse guard replaces `spawn` on the module;
# `start` goes through the module attribute, so it meets the guard when there is one.
HEADER = """\
import subprocess
import sys

import pytest

from agent_build_kit.runtimes import claude_code

original_spawn = claude_code.spawn
HARMLESS = [sys.executable, "-c", "print('ran')"]


def start():
    return claude_code.spawn(HARMLESS)
"""

UNMARKED = (
    HEADER
    + """

def test_unmarked_spawn():
    start()


@pytest.mark.local_stack
def test_marked_spawn():
    assert start().returncode == 0
"""
)

MARKED = (
    HEADER
    + """

@pytest.mark.local_stack
def test_marked_spawn():
    assert claude_code.spawn is original_spawn
    done = start()
    assert done.returncode == 0
    assert done.stdout.strip() == "ran"


@pytest.mark.local_stack
class TestMarkedClass:
    def test_spawn(self):
        assert claude_code.spawn is original_spawn
        assert start().returncode == 0
"""
)

MODULE_MARKED = (
    HEADER
    + """
pytestmark = pytest.mark.local_stack


def test_module_marked_spawn():
    assert claude_code.spawn is original_spawn
    assert start().stdout.strip() == "ran"
"""
)

CLAUDE = (
    HEADER
    + """

def test_unmarked_claude():
    subprocess.run(["claude"], check=False)


@pytest.mark.local_stack
def test_marked_claude():
    assert subprocess.run(["claude"], check=False).returncode == 0
"""
)

OTHER_GUARDS = (
    HEADER
    + """
from agent_build_kit import forges
from agent_build_kit.forges import github


@pytest.fixture(autouse=True)
def lifted():
    # the marked test is let through the agent guards before the others are tried
    assert start().returncode == 0


@pytest.mark.local_stack
def test_refresh_is_refused():
    with pytest.raises(AssertionError, match="refresh the login"):
        claude_code.refresh_login()


@pytest.mark.local_stack
def test_usage_reading_is_refused():
    with pytest.raises(AssertionError, match="real usage window"):
        claude_code.read_live_usage()


@pytest.mark.local_stack
def test_gh_is_refused():
    with pytest.raises(AssertionError, match="real gh command: gh auth status"):
        subprocess.run(["gh", "auth", "status"], check=False)


@pytest.mark.local_stack
def test_code_host_is_the_stand_in():
    assert forges.get("github") is not github.FORGE
"""
)


@pytest.fixture
def child(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str], pytest.RunResult]:
    """Runs a source file in a child pytest under the real guards."""
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    pytester.makeini(INI)
    pytester.makeconftest(CONFTEST)

    def run(source: str) -> pytest.RunResult:
        pytester.makepyfile(test_child=source)
        return pytester.runpytest_subprocess("-p", "no:cacheprovider", "-q")

    return run


def test_an_unmarked_test_that_starts_the_real_spawn_is_refused(
    child: Callable[[str], pytest.RunResult],
) -> None:
    result = child(UNMARKED)

    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(
        [
            "*a test tried to spawn a real agent process*",
            "*FAILED test_child.py::test_unmarked_spawn*",
        ]
    )


def test_a_marked_test_starts_a_program_through_the_original_spawn(
    child: Callable[[str], pytest.RunResult],
) -> None:
    result = child(MARKED)

    result.assert_outcomes(passed=2)


def test_a_module_level_mark_gives_the_same_result(
    child: Callable[[str], pytest.RunResult],
) -> None:
    result = child(MODULE_MARKED)

    result.assert_outcomes(passed=1)


def test_claude_is_refused_for_an_unmarked_test_and_not_for_a_marked_one(
    child: Callable[[str], pytest.RunResult],
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = pytester.mkdir("bin")
    script = bin_dir / "claude"
    script.write_text(f"#!{sys.executable}\nraise SystemExit(0)\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    result = child(CLAUDE)

    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(
        ["*a test spawned `claude` directly*", "*FAILED test_child.py::test_unmarked_claude*"]
    )


def test_the_other_guards_hold_for_a_marked_test(
    child: Callable[[str], pytest.RunResult],
) -> None:
    result = child(OTHER_GUARDS)

    result.assert_outcomes(passed=4)
