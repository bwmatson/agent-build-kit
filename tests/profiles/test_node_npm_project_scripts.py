"""The node-npm whole-folder lint and clean check follow the project's own `lint` and
`format:check` scripts (spec: node-npm-lint-and-test).

Each case runs the profile's command for real in a git repository, with `npm` and `npx`
replaced by programs that record the call they were given, one line per call.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit import profiles
from tests.factories import git, init_repo

GENERIC_LINT = "npx oxlint ."
GENERIC_FORMAT = "npx oxfmt --check ."
GENERIC_TYPES = "npx tsc --noEmit"
SCRIPT_LINT = "npm run lint"
SCRIPT_FORMAT = "npm run format:check"

# `npm run` stands for a project script scoped to the folders the project owns, so it passes;
# the generic format check looks at the whole folder and fails on the malformatted document.
FAKE_TOOL = """\
#!/bin/sh
echo "$(basename "$0") $*" >> "$CALLS"
if [ "$(basename "$0")" = npx ] && [ "$1 $2 $3" = "oxfmt --check ." ] \\
   && grep -q malformatted README.md 2>/dev/null; then
  exit 1
fi
exit 0
"""

LINT = {"lint": "oxlint src"}
FORMAT = {"format:check": "oxfmt --check src"}

# Each kind of project: its `scripts` and the calls the whole-folder lint makes in it. The
# generic-only kinds already behave so; one test covers every kind, so it fails until the
# script-following kinds do.
CHOICES: dict[str, tuple[dict[str, str] | None, list[str]]] = {
    "both scripts": ({**LINT, **FORMAT}, [SCRIPT_LINT, SCRIPT_FORMAT]),
    "only lint": (LINT, [SCRIPT_LINT, GENERIC_FORMAT]),
    "only format:check": (FORMAT, [GENERIC_LINT, SCRIPT_FORMAT]),
    "neither script": ({"build": "tsc"}, [GENERIC_LINT, GENERIC_FORMAT]),
    "no scripts field": (None, [GENERIC_LINT, GENERIC_FORMAT]),
}
EXPECTED = {name: expected for name, (_, expected) in CHOICES.items()}


@pytest.fixture
def profile():
    return profiles.get("node-npm")


@pytest.fixture
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The file the recording `npm` and `npx`, first on the path, append their calls to."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("npm", "npx"):
        program = bin_dir / name
        program.write_text(FAKE_TOOL)
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CALLS", str(log))
    return log


def make_project(where: Path, scripts: dict[str, str] | None, *, malformatted: bool = True) -> Path:
    """A project in a git repository at `where` whose `package.json` has `scripts` (no field
    when None), with a malformatted document outside the folder the scripts cover."""
    work = init_repo(where)
    manifest: dict[str, object] = {"name": "app", "version": "1.0.0"}
    if scripts is not None:
        manifest["scripts"] = scripts
    (work / "package.json").write_text(json.dumps(manifest))
    (work / "src").mkdir()
    (work / "src/a.ts").write_text("export const a = 1;\n")
    (work / "README.md").write_text("malformatted   document\n" if malformatted else "fine\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    return work


def run(command: list[str] | str, where: Path, log: Path) -> tuple[int, list[str]]:
    """The exit status of `command` in `where` and the calls the tools recorded."""
    log.unlink(missing_ok=True)
    done = subprocess.run(
        command if isinstance(command, list) else ["sh", "-c", command],
        cwd=where,
        capture_output=True,
    )
    return done.returncode, log.read_text().splitlines() if log.exists() else []


def calls_per_choice(
    command: Callable[[], list[str] | str], tmp_path: Path, log: Path
) -> dict[str, list[str]]:
    """The calls `command()` makes in a project of each kind in CHOICES."""
    made = {}
    for index, (name, (scripts, _)) in enumerate(CHOICES.items()):
        project = make_project(tmp_path / f"project{index}", scripts, malformatted=False)
        made[name] = run(command(), project, log)[1]
    return made


def test_the_all_files_lint_runs_the_scripts_the_project_defines_and_the_generic_tool_for_the_rest(
    profile, tmp_path: Path, calls: Path
) -> None:
    assert calls_per_choice(profile.lint_command_all_files, tmp_path, calls) == EXPECTED


def test_the_clean_command_runs_the_same_lint_and_format_commands_as_the_all_files_lint(
    profile, tmp_path: Path, calls: Path
) -> None:
    assert calls_per_choice(profile.clean_command, tmp_path, calls) == EXPECTED


def test_the_clean_command_with_types_adds_the_type_check_after_the_same_commands(
    profile, tmp_path: Path, calls: Path
) -> None:
    made = calls_per_choice(lambda: profile.clean_command(types=True), tmp_path, calls)

    assert made == {name: [*expected, GENERIC_TYPES] for name, expected in EXPECTED.items()}


def test_a_malformatted_file_outside_the_scripts_scope_does_not_fail_the_all_files_checks(
    profile, tmp_path: Path, calls: Path
) -> None:
    project = make_project(tmp_path / "project", {**LINT, **FORMAT})

    lint_status, _ = run(profile.lint_command_all_files(), project, calls)
    clean_status, _ = run(profile.clean_command(types=True), project, calls)

    assert lint_status == 0
    assert clean_status == 0
