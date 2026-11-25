"""A unit-test run that fails, as the processes answer it, for the tests of the failure bundle.

`BundleMachine` answers git, lint, the version query and the test run; the run itself removes one
file under `tests/` and adds another, as something else on the host might. A test run prints what
a `-q` run prints: no header. It runs in the `scratch` checkout of `tests/pipeline/conftest.py`.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import flake_record
from agent_build_kit.pipeline.run_log import TEST_TRACE_VARIABLE
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.e2e_base_fakes import pytest_output

RECORDED = Path(__file__).resolve().parent / "fixtures" / "external" / "pytest"
START = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
# What `pytest --version --version` printed, as recorded: the profile queries it because a `-q`
# run prints no header.
VERSIONS = (RECORDED / "version_verbose.txt").read_text()


def run_ledger_rows(path: Path) -> list[dict]:
    """The rows of a ledger of unit-test runs (`runs/test-runs.jsonl`), as written."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def storms(installation: Installation) -> list[dict]:
    """The storm rows of the flake record, as written."""
    try:
        lines = flake_record(installation).path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    rows = [json.loads(line) for line in lines if line.strip()]
    return [row for row in rows if row.get("kind") == "storm"]


class BundleProfile(PythonUvProfile):
    """The python-uv profile with one lint command; its test commands are its own."""

    def lint_command(self, base: str) -> list[str]:
        return ["lint"]


class BundleMachine:
    """Git, lint, the version query and the test run as the processes answer."""

    def __init__(
        self,
        root: Path,
        *,
        reruns: list[int],
        passing: bool = False,
        traces: list[str | None] | None = None,
    ) -> None:
        self.root = root
        self.reruns = list(reruns)
        self.passing = passing
        self.status_calls = 0
        self.commands: list[list[str]] = []
        # What the workers of each test run write to the trace file the run's environment names,
        # in the order the runs come (the full run, then each rerun); None writes none.
        self.traces = list(traces or [])
        # The trace file each test run's environment named, in the same order.
        self.trace_paths: list[str] = []

    def _worker_writes(self, kwargs: dict[str, object]) -> None:
        """The workers of a test run, writing their trace to the file the environment names."""
        env = kwargs.get("env")
        named = env.get(TEST_TRACE_VARIABLE) if isinstance(env, dict) else None
        if named is None:
            return
        self.trace_paths.append(named)
        text = self.traces.pop(0) if self.traces else None
        if text is not None:
            Path(named).parent.mkdir(parents=True, exist_ok=True)
            Path(named).write_text(text, encoding="utf-8")

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        if command == ["lint"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["git", "status"]:
            self.status_calls += 1
            return subprocess.CompletedProcess(
                command, 0, f" M src/file{self.status_calls}.py\n", ""
            )
        if command[:2] == ["git", "rev-parse"]:
            sha = "b" * 7 if command[-1] == "main" else "a" * 7
            return subprocess.CompletedProcess(command, 0, sha + "\n", "")
        if command[-2:] == ["--version", "--version"]:
            return subprocess.CompletedProcess(command, 0, VERSIONS, "")
        self._worker_writes(kwargs)
        if any("::" in argument for argument in command):
            return subprocess.CompletedProcess(command, self.reruns.pop(0), "1 passed\n", "")
        if self.passing:
            return subprocess.CompletedProcess(command, 0, "5 passed in 0.03s\n", "")
        (self.root / "tests" / "test_gone.py").unlink(missing_ok=True)
        (self.root / "tests" / "test_new.py").write_text("")
        failure = (RECORDED / "console_failures.txt").read_text().split("\n", 1)[1]
        return subprocess.CompletedProcess(command, 1, failure, "")


class RerunMachine(BundleMachine):
    """`BundleMachine` whose runs by test id print what pytest prints for those ids: a failure
    line per id when the run exits non-zero, a pass otherwise. `serial` keeps each such run with
    the keyword arguments it was given."""

    def __init__(self, root: Path, *, reruns: list[int]) -> None:
        super().__init__(root, reruns=reruns)
        self.serial: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        ids = [argument for argument in command if "::" in argument]
        if not ids:
            return super().__call__(command, **kwargs)
        self.commands.append(command)
        self.serial.append((command, kwargs))
        exit_code = self.reruns.pop(0)
        failed = {test: "assert 1 == 2" for test in ids} if exit_code else {}
        output = pytest_output(failed=failed, passed=() if exit_code else tuple(ids))
        return subprocess.CompletedProcess(command, exit_code, output, "")
