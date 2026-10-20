"""A scheduled split whose tests all need an unavailable value is skipped with a note naming
it, fails nothing and parks nothing; a split with some runnable tests runs only those (spec:
e2e-dimensions, "The scheduler runs what is runnable")."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.config import REST_SPLIT, E2eDimensionValue, E2eSplit, E2eUnitScope
from agent_build_kit.pipeline.wiring import E2eSession
from tests.e2e_base_fakes import pytest_output
from tests.e2e_check_support import marker_matches
from tests.e2e_scope_fakes import Ran, branch
from tests.e2e_scope_fakes import session as shared_session

MARKER = "local_stack"
SPLITS = (
    E2eSplit(name="acp", marker="runtime_acp"),
    E2eSplit(name="claude_code", marker="runtime_claude_code"),
    E2eSplit(name=REST_SPLIT),
)
DIMENSIONS = {
    "telemetry": {
        "otel": E2eDimensionValue(marker="telemetry_otel"),
        "local": E2eDimensionValue(marker="telemetry_local"),
    }
}
UNAVAILABLE = ["telemetry_otel"]
# The markers each test of the fixture repository carries besides the e2e marker: every test of
# `acp` needs otel, `claude_code` has one test that does and one that does not.
ACP = "tests/live/test_acp.py::test_acp"
CLAUDE_OTEL = "tests/live/test_claude.py::test_with_otel"
CLAUDE_PLAIN = "tests/live/test_claude.py::test_plain"
TAGS: dict[str, set[str]] = {
    ACP: {"runtime_acp", "telemetry_otel"},
    CLAUDE_OTEL: {"runtime_claude_code", "telemetry_otel"},
    CLAUDE_PLAIN: {"runtime_claude_code"},
}
FILES = {
    "tests/live/test_acp.py": "def test_acp():\n    assert True\n",
    "tests/live/test_claude.py": (
        "def test_with_otel():\n    assert True\n\ndef test_plain():\n    assert True\n"
    ),
}


class Collecting(Ran):
    """A pytest-shaped runner over the fixture repository: it lists what a command's `-m`
    expression selects when asked to collect, and otherwise runs those and passes them."""

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append((command, Path(str(kwargs["cwd"]))))
        expression = command[command.index("-m") + 1]
        chosen = [
            test for test, tags in TAGS.items() if marker_matches(expression, {MARKER, *tags})
        ]
        if "--collect-only" in command:
            return subprocess.CompletedProcess(
                command, 0 if chosen else 5, "".join(f"{t}\n" for t in chosen), ""
            )
        return subprocess.CompletedProcess(command, 0, pytest_output(passed=tuple(chosen)), "")

    @property
    def runs(self) -> list[list[str]]:
        return [c for c in self.commands if "--collect-only" not in c and "-m" in c]


def scheduled(tmp_path: Path, ran: Collecting, log: list[str]) -> tuple[E2eSession, Path, str]:
    """The session of a scheduled run of one split on the default branch, whole."""
    repo, base = branch(tmp_path, None, base_files=FILES)
    gate = shared_session(
        tmp_path,
        ran,
        scope=E2eUnitScope.FULL,
        log=log,
        splits=SPLITS,
        unavailable=UNAVAILABLE,
        dimensions=DIMENSIONS,
    )
    return gate, repo, base


def test_a_split_with_nothing_runnable_is_skipped_naming_the_value_and_fails_nothing(
    tmp_path: Path,
) -> None:
    ran, log = Collecting(), []
    gate, repo, base = scheduled(tmp_path, ran, log)

    ok, _ = gate.run(cwd=repo, base=base, only="acp")

    assert ok
    assert any("nothing runnable: needs telemetry=otel" in line for line in log), log
    assert ran.runs == []
    assert gate.result is not None
    assert (gate.result.failed, gate.result.parked, gate.result.ran_no_tests) == (0, [], True)


def test_a_split_with_some_runnable_tests_runs_only_those(tmp_path: Path) -> None:
    ran, log = Collecting(), []
    gate, repo, base = scheduled(tmp_path, ran, log)

    skipped, _ = gate.run(cwd=repo, base=base, only="acp")
    ok, _ = gate.run(cwd=repo, base=base, only="claude_code")

    assert skipped and ok
    assert sum("nothing runnable" in line for line in log) == 1, "only the first split is skipped"
    [run] = ran.runs
    assert "not telemetry_otel" in run[run.index("-m") + 1]
    assert gate.result is not None
    assert (gate.result.passed, gate.result.failed) == (1, 0)
