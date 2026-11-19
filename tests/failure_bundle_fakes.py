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
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.time_limit import TRACE_VARIABLE

RECORDED = Path(__file__).resolve().parent / "fixtures" / "external" / "pytest"
START = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)
# What `pytest --version --version` printed, as recorded: the profile queries it because a `-q`
# run prints no header.
VERSIONS = (RECORDED / "version_verbose.txt").read_text()


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
        named = env.get(TRACE_VARIABLE) if isinstance(env, dict) else None
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
