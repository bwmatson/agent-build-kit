"""The node-npm profile's clean and red commands (spec: node-npm-red-and-stubs).

Both commands run for real, in a project directory, with `npx` replaced by a program that
records the arguments it was given, one per line, and, when told where to write a JUnit
report with `--outputFile`, writes a recorded Vitest report there and exits as a red run does.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.red_check import parse_report, split_report

VITEST = Path(__file__).resolve().parents[1] / "fixtures" / "external" / "vitest"

FAKE_NPX = """\
#!/bin/sh
# Stands in for npx: keeps the call, writes the recorded report where it is told to.
{ echo "--- call"; printf '%s\\n' "$@"; } >> "$CALLS"
for arg in "$@"; do
  case "$arg" in
    --outputFile=*) cp "$RECORDING" "${arg#*=}"; exit 1 ;;
  esac
done
exit "${FAIL_TOOL_EXIT:-0}"
"""

FILES = ["src/a.test.ts", "packages/ui/b.spec.tsx"]


@pytest.fixture
def profile():
    return profiles.get("node-npm")


class Project:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = root / "calls.log"
        self.scratch = root / "scratch"

    def run(self, command: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            shell=True,
            cwd=self.root / "project",
            capture_output=True,
            text=True,
            check=False,
            env={
                **os.environ,
                "PATH": f"{self.root / 'bin'}{os.pathsep}{os.environ['PATH']}",
                "TMPDIR": str(self.scratch),
                "CALLS": str(self.calls),
                "RECORDING": str(VITEST / "assertion.xml"),
                **env,
            },
        )

    def calls_made(self) -> list[list[str]]:
        """The argument lists `npx` was called with, in order."""
        if not self.calls.exists():
            return []
        chunks = self.calls.read_text().split("--- call\n")[1:]
        return [chunk.splitlines() for chunk in chunks]


@pytest.fixture
def project(tmp_path: Path) -> Project:
    (tmp_path / "bin").mkdir()
    npx = tmp_path / "bin" / "npx"
    npx.write_text(FAKE_NPX)
    npx.chmod(npx.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "project").mkdir()
    (tmp_path / "scratch").mkdir()
    return Project(tmp_path)


def test_the_clean_command_lints_and_checks_the_format_and_does_not_type_check(
    profile, project: Project
) -> None:
    done = project.run(profile.clean_command())

    assert done.returncode == 0, done.stderr
    tools = [call[0] for call in project.calls_made()]
    assert "oxlint" in tools
    assert any(call[0] == "oxfmt" and "--check" in call for call in project.calls_made())
    assert "tsc" not in tools


def test_a_lint_failure_fails_the_clean_command(profile, project: Project) -> None:
    done = project.run(profile.clean_command(), FAIL_TOOL_EXIT="1")

    assert done.returncode != 0


def test_the_red_command_runs_exactly_the_given_files(profile, project: Project) -> None:
    project.run(profile.red_command(FILES))

    (call,) = project.calls_made()
    assert call[0] == "vitest" and call[1] == "run"
    assert [arg for arg in call[2:] if not arg.startswith("-")] == FILES


def test_the_red_runs_exit_status_is_the_runners_and_the_report_outlives_its_file(
    profile, project: Project
) -> None:
    done = project.run(profile.red_command(FILES))

    assert done.returncode == 1
    report, console = split_report(done.stdout + done.stderr)
    assert report is not None, "the report is in the output"
    suites = parse_report(report)
    assert suites.tag == "testsuites" and list(suites.iter("failure"))
    assert list(project.scratch.iterdir()) == [], "the temporary file is gone"
    assert "<testsuites" not in console
