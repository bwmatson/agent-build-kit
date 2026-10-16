"""The node-npm profile runs the tests and reads the report (spec: node-npm-lint-and-test).

Every parser reads a Vitest recording under `tests/fixtures/external/vitest/`. The test
command runs for real with `npx` replaced by a program that does what Vitest does with the
arguments the command gives it: it writes a recorded JUnit report to the file named by
`--outputFile`, exits as the recorded run did, and, with no test files in the project, fails
unless it was told to pass with none.
"""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.e2e import TestFailure
from agent_build_kit.pipeline.red_check import REPORT_MARK

VITEST = Path(__file__).resolve().parents[1] / "fixtures" / "external" / "vitest"

FAKE_NPX = """\
#!/bin/sh
# Stands in for npx running Vitest.
out=""
pass_with_none=no
prev=""
for arg in "$@"; do
  case "$arg" in
    --outputFile=*|--outputFile.junit=*) out="${arg#*=}" ;;
    --passWithNoTests) pass_with_none=yes ;;
  esac
  case "$prev" in
    --outputFile|--outputFile.junit) out="$arg" ;;
  esac
  prev="$arg"
done
if [ -z "$(find . -name '*.test.*' -not -path './node_modules/*' | head -n 1)" ]; then
  [ "$pass_with_none" = yes ] && exit 0
  echo "No test files found, exiting with code 1" >&2
  exit 1
fi
[ -n "$out" ] && cp "$RECORDING" "$out"
exit "$RECORDED_EXIT"
"""


@pytest.fixture
def profile():
    return profiles.get("node-npm")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project with one test file, with `npx` replaced by the fake Vitest."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npx = bin_dir / "npx"
    npx.write_text(FAKE_NPX)
    npx.chmod(npx.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    work = tmp_path / "project"
    (work / "src").mkdir(parents=True)
    (work / "package.json").write_text("{}\n")
    (work / "src" / "a.test.ts").write_text("// a test\n")
    return work


def recording(name: str) -> str:
    return (VITEST / name).read_text()


def printed(name: str) -> str:
    """What the test command prints for the recorded run: console output, then the report
    after the marker."""
    return f"RUN v5.0.4\n{REPORT_MARK}\n{recording(name)}"


def commands(profile, work: Path) -> list[list[str]]:
    return profile.test_commands(work, ["src/a.ts"], root_extras=[])


def run(profile, work: Path, name: str | None, code: int) -> tuple[list[str], str, int]:
    (command,) = commands(profile, work)
    env = {**os.environ, "RECORDED_EXIT": str(code), "RECORDING": str(VITEST / (name or ""))}
    done = subprocess.run(command, cwd=work, capture_output=True, text=True, env=env, check=False)
    return command, done.stdout + done.stderr, done.returncode


def test_the_summary_comes_from_the_recorded_report(profile) -> None:
    passed, failed, skipped, _ = profile.parse_test_summary(printed("assertion.xml"))

    assert (passed, failed, skipped) == (1, 1, 1)


def test_a_recorded_passing_run_summarises_with_no_failures(profile) -> None:
    passed, failed, skipped, _ = profile.parse_test_summary(printed("passing.xml"))

    assert (passed, failed, skipped) == (2, 0, 0)
    assert profile.parse_test_failures(printed("passing.xml")) == []


def test_each_failing_test_is_returned_with_its_name_and_location(profile) -> None:
    (failure,) = profile.parse_test_failures(printed("assertion.xml"))

    assert isinstance(failure, TestFailure)
    assert "adds" in failure.test
    assert "a.test.ts" in failure.test + failure.line


def test_a_failure_of_a_not_implemented_stub_is_returned_with_its_message(profile) -> None:
    (failure,) = profile.parse_test_failures(printed("not_implemented.xml"))

    assert "creates" in failure.test
    assert "b.test.ts" in failure.test + failure.line
    assert "not implemented" in failure.line


def test_a_test_file_that_cannot_import_its_subject_is_a_failed_run_naming_the_file(
    profile,
) -> None:
    _, failed, _, _ = profile.parse_test_summary(printed("missing_import.xml"))
    (failure,) = profile.parse_test_failures(printed("missing_import.xml"))

    assert failed >= 1
    assert "c.test.ts" in failure.test
    assert "nothing" in failure.line


def test_a_type_error_in_a_test_file_is_not_a_test_failure_because_vitest_strips_types(
    profile,
) -> None:
    """The recording shows what Vitest does with a type error: it runs the test and passes.
    That is why the type check is a check of its own (`project_checks`)."""
    passed, failed, _, _ = profile.parse_test_summary(printed("type_error.xml"))

    assert (passed, failed) == (1, 0)
    assert profile.parse_test_failures(printed("type_error.xml")) == []


def test_a_project_with_no_test_files_passes(profile, project: Path) -> None:
    (project / "src" / "a.test.ts").unlink()

    command, output, code = run(profile, project, None, 1)

    assert code == 0, output
    assert profile.tolerates_exit(command, code)


def test_a_failing_test_fails_the_command_and_is_classified_as_test(profile, project: Path) -> None:
    command, output, code = run(profile, project, "assertion.xml", 1)

    assert not profile.tolerates_exit(command, code)
    failed = f"$ {shlex.join(command)} (exit {code})\n(in {project})\n{output}"
    assert profile.failure_kind(failed) == "test"


def test_the_report_is_still_in_the_output_after_the_commands_temporary_file_is_gone(
    profile, project: Path
) -> None:
    _, output, code = run(profile, project, "assertion.xml", 1)

    assert code == 1
    assert REPORT_MARK in output
    assert profile.parse_test_summary(output)[:3] == (1, 1, 1)
    assert [f.test for f in profile.parse_test_failures(output)] != []
