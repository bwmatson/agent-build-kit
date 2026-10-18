"""The node-npm profile lints, checks format and type-checks (spec: node-npm-lint-and-test).

The lint commands run for real in a git repository, with the tools replaced by programs
that record their arguments: what the command names is what the linter would have been
given. The failure outputs are what the tools print, behind the `$ command (exit N)` line
unit-test puts above a failed command's output.
"""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import RepoConfig
from tests.factories import git, init_repo

TOOLS = ("npx", "oxlint", "oxfmt", "tsc")

OXLINT_ERROR = """\
  x eslint(no-unused-vars): Variable 'unused' is declared but never used.
   ,-[src/a.ts:1:7]
 1 | const unused = 1;
   :       ^^^|^^^
   :          `-- 'unused' is declared but never used.
   `----
  help: Consider removing this declaration.

Found 0 warnings and 1 error.
Finished in 4ms on 1 file with 93 rules using 8 threads.
"""

OXFMT_ERROR = """\
Checking formatting...

src/a.ts
Format issues found in above 1 files. Run without `--check` to fix.
Finished in 3ms on 1 files using 8 threads.
"""

TSC_ERROR = (
    "src/a.ts(2,7): error TS2322: Type 'string' is not assignable to type 'number'.\n"
    "\n"
    "Found 1 error in src/a.ts:2\n"
)


@pytest.fixture
def profile():
    return profiles.get("node-npm")


@pytest.fixture
def tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Programs named as the tools are that append their own name and arguments, one per
    line, to the returned file, ahead of everything else on the path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "args.log"
    for name in TOOLS:
        program = bin_dir / name
        program.write_text(
            f'#!/bin/sh\nprintf "%s\\n" "$(basename "$0")" "$@" >> {shlex.quote(str(log))}\n'
        )
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return log


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project on a branch that changes one source file and one document."""
    work = init_repo(tmp_path / "project")
    for name in ("src/a.ts", "src/b.ts", "README.md"):
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text("as committed\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    git(work, "switch", "-qc", "unit")
    (work / "src/a.ts").write_text("changed\n")
    (work / "README.md").write_text("changed\n")
    git(work, "commit", "-qam", "unit")
    return work


@pytest.fixture
def nested_project(tmp_path: Path) -> Path:
    """The project `web` in a repo that holds a second one, `api`; the branch changes a
    source file in each. Returns the directory unit-test runs the project's commands in."""
    work = init_repo(tmp_path / "repo")
    for name in ("web/src/a.ts", "web/src/b.ts", "api/b.ts", "api/c.ts"):
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text("as committed\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    git(work, "switch", "-qc", "unit")
    (work / "web/src/a.ts").write_text("changed\n")
    (work / "api/b.ts").write_text("changed\n")
    git(work, "commit", "-qam", "unit")
    return work / "web"


def run_command(command: list[str], where: Path, log: Path) -> list[str]:
    """The arguments every tool the command started was given, as `log` recorded them."""
    subprocess.run(command, cwd=where, check=True, capture_output=True)
    return log.read_text().splitlines() if log.exists() else []


def covers(args: list[str], path: str) -> bool:
    """Whether some argument names `path`, or a directory holding it."""
    return any(
        arg in (path, ".", "./") or path.startswith(arg.rstrip("/") + "/")
        for arg in args
        if not arg.startswith("-")
    )


def failure(command: list[str], printed: str, code: int = 1) -> str:
    return f"$ {shlex.join(command)} (exit {code})\n(in /work/project)\n{printed}"


def test_the_lint_command_for_a_diff_names_the_changed_source_file_and_no_other(
    profile, project: Path, tools: Path
) -> None:
    args = run_command(profile.lint_command("main"), project, tools)

    assert "src/a.ts" in args
    assert "src/b.ts" not in args
    assert "README.md" not in args


def test_the_lint_command_in_a_subdirectory_names_its_own_changed_file_relative_to_it(
    profile, nested_project: Path, tools: Path
) -> None:
    args = run_command(profile.lint_command("main"), nested_project, tools)

    assert "src/a.ts" in args
    assert "web/src/a.ts" not in args
    assert not any(arg.endswith("b.ts") for arg in args)


def test_the_lint_command_checks_both_the_lint_and_the_format(
    profile, project: Path, tools: Path
) -> None:
    args = run_command(profile.lint_command("main"), project, tools)

    assert "oxlint" in args
    assert "oxfmt" in args
    assert "--check" in args


def test_a_base_that_does_not_resolve_fails_the_lint_without_running_a_tool(
    profile, project: Path, tools: Path
) -> None:
    done = subprocess.run(
        profile.lint_command("no-such-ref"), cwd=project, capture_output=True, text=True
    )

    assert done.returncode != 0
    assert "no-such-ref" in done.stderr
    assert not tools.exists()


def test_the_all_files_lint_command_covers_the_whole_project(
    profile, project: Path, tools: Path
) -> None:
    args = run_command(profile.lint_command_all_files(), project, tools)

    assert covers(args, "src/a.ts")
    assert covers(args, "src/b.ts")


def test_recorded_lint_output_with_an_error_fails_and_is_classified_as_lint(profile) -> None:
    command = profile.lint_command("main")

    assert not profile.tolerates_exit(command, 1)
    assert profile.failure_kind(failure(command, OXLINT_ERROR)) == "lint"


def test_a_base_ref_naming_the_type_checker_does_not_make_a_lint_failure_types(profile) -> None:
    command = profile.lint_command("spec/tsconfig-paths/1")

    assert profile.failure_kind(failure(command, OXLINT_ERROR)) == "lint"


def test_a_base_ref_naming_the_test_runner_does_not_make_a_lint_failure_a_test(profile) -> None:
    command = profile.lint_command("origin/spec/move-to-vitest/1")

    assert profile.failure_kind(failure(command, OXLINT_ERROR)) == "lint"


def test_recorded_format_output_with_an_error_is_classified_as_lint(profile) -> None:
    command = profile.lint_command("main")

    assert profile.failure_kind(failure(command, OXFMT_ERROR)) == "lint"


def test_recorded_type_check_output_with_an_error_fails_and_is_classified_as_types(
    profile, tmp_path: Path
) -> None:
    (command,) = profile.project_checks(RepoConfig(path=tmp_path))

    assert not profile.tolerates_exit(command, 2)
    assert profile.failure_kind(failure(command, TSC_ERROR, 2)) == "types"


def test_a_clean_type_check_passes(profile, tmp_path: Path) -> None:
    (command,) = profile.project_checks(RepoConfig(path=tmp_path))

    assert profile.tolerates_exit(command, 0)
