"""The node-npm profile driven against a real npm workspace (spec: node-npm-workspaces).

A temporary workspace of two packages, `core` and `app` (which depends on `core`), is installed
from the npm registry, and the profile's own commands are built and run in it: lint, the type
check, the tests of a changed member and the tier-2 run for the file-name marker. A failure
seeded in one member fails the matching command with the failure kind the profile reports for
it, and the dependents of the shared package are read from the manifests.

This is the one test that reaches the npm registry: the point is a real install and a real
runner. Needs node and npm; skipped when either is absent. Marked e2e-test and excluded from the
default suite; run it with
`uv run pytest -m local_stack tests/integration/test_node_npm_workspace.py`.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.profiles.node_npm import PROFILE

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(
        shutil.which("node") is None or shutil.which("npm") is None,
        reason="node and npm are not on PATH; the workspace test needs both",
    ),
]

MARKER = "local_stack"
CORE = "packages/core"
APP = "packages/app"
# The fixture's files are written as oxfmt prints them, so its format check has nothing to fix.
ROOT_MANIFEST = """{
  "name": "workspace",
  "private": true,
  "type": "module",
  "devDependencies": {
    "oxfmt": "*",
    "oxlint": "^1",
    "typescript": "^5",
    "vitest": "^3"
  },
  "workspaces": ["packages/*"]
}
"""
TSCONFIG = """{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true
  },
  "include": ["packages/*/src"]
}
"""
CORE_MANIFEST = """{
  "name": "@ws/core",
  "version": "1.0.0",
  "main": "src/add.ts",
  "types": "src/add.ts"
}
"""
APP_MANIFEST = """{
  "name": "@ws/app",
  "version": "1.0.0",
  "dependencies": {
    "@ws/core": "*"
  }
}
"""
FILES = {
    "package.json": ROOT_MANIFEST,
    "tsconfig.json": TSCONFIG,
    ".gitignore": "node_modules\n",
    f"{CORE}/package.json": CORE_MANIFEST,
    f"{CORE}/src/add.ts": "export function add(a: number, b: number): number {\n"
    "  return a + b;\n}\n",
    f"{CORE}/src/add.test.ts": 'import { expect, test } from "vitest";\n'
    'import { add } from "./add";\n\n'
    'test("adds", () => {\n  expect(add(1, 2)).toBe(3);\n});\n',
    f"{CORE}/src/add.{MARKER}.test.ts": 'import { expect, test } from "vitest";\n'
    'import { add } from "./add";\n\n'
    'test("adds on the stack", () => {\n  expect(add(2, 2)).toBe(4);\n});\n',
    f"{APP}/package.json": APP_MANIFEST,
    f"{APP}/src/total.ts": 'import { add } from "@ws/core";\n\n'
    "export function total(values: number[]): number {\n"
    "  return values.reduce(add, 0);\n}\n",
    f"{APP}/src/total.test.ts": 'import { expect, test } from "vitest";\n'
    'import { total } from "./total";\n\n'
    'test("totals", () => {\n  expect(total([1, 2, 3])).toBe(6);\n});\n',
}
TOTAL_TEST = f"{APP}/src/total.test.ts"
TOTAL = f"{APP}/src/total.ts"
ADD_TEST = f"{CORE}/src/add.test.ts"


def run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
        env={**os.environ, "npm_config_yes": "true", "CI": "true"},
    )


def report(argv: list[str], done: subprocess.CompletedProcess[str]) -> str:
    """What the pipeline hands `failure_kind`: the command's header, then what it printed."""
    return f"$ {shlex.join(argv)} (exit {done.returncode})\n{done.stdout}{done.stderr}"


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("npm-workspace")
    for relative, content in FILES.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(content)
    installed = run(["npm", "install", "--no-audit", "--no-fund"], root)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    # The manifests are left as the formatter prints them, whatever order it keeps their keys in.
    formatted = run(["npx", "oxfmt", "."], root)
    assert formatted.returncode == 0, formatted.stdout + formatted.stderr
    return root


@contextmanager
def seeded(root: Path, relative: str, content: str) -> Iterator[None]:
    """`relative` holds `content` inside the block and its old content after it."""
    path = root / relative
    before = path.read_text()
    path.write_text(content)
    try:
        yield
    finally:
        path.write_text(before)


def run_all(commands: list[list[str]], root: Path) -> list[subprocess.CompletedProcess[str]]:
    return [run(command, root) for command in commands]


def test_a_clean_workspace_passes_lint_and_the_type_check(workspace: Path) -> None:
    for argv in (
        PROFILE.lint_command_all_files(),
        *PROFILE.project_checks(RepoConfig(path=workspace)),
    ):
        done = run(argv, workspace)
        assert done.returncode == 0, report(argv, done)


def test_the_members_and_the_dependents_of_the_shared_package_are_read_from_the_manifests(
    workspace: Path,
) -> None:
    assert PROFILE.members(workspace) == [APP, CORE]
    assert PROFILE.dependents(workspace, CORE) == [APP]
    assert PROFILE.dependents(workspace, APP) == []
    assert PROFILE.member_of(workspace, TOTAL) == APP


def test_a_change_in_one_member_runs_that_members_tests_and_they_pass(workspace: Path) -> None:
    commands = PROFILE.test_commands(workspace, [ADD_TEST], root_extras=[])

    assert len(commands) == 1
    assert CORE in commands[0]
    done = run(commands[0], workspace)
    assert done.returncode == 0, report(commands[0], done)
    passed, failed, _, _ = PROFILE.parse_test_summary(done.stdout + done.stderr)
    # The member's whole run, marked file included; the app's test is not in it.
    assert (passed, failed) == (2, 0)


def test_a_change_to_the_root_manifest_runs_every_member(workspace: Path) -> None:
    commands = PROFILE.test_commands(workspace, ["package.json"], root_extras=[])

    assert len(commands) == 2
    for done in run_all(commands, workspace):
        assert done.returncode == 0, done.stdout + done.stderr


def test_the_tier_2_run_selects_the_marked_files_and_not_the_unmarked_ones(
    workspace: Path,
) -> None:
    ran: list[str] = []
    for argv in PROFILE.e2e_commands(workspace, marker=MARKER):
        done = run(argv, workspace)
        assert done.returncode == 0, report(argv, done)
        ran += [t.test for t in PROFILE.parse_test_durations(done.stdout + done.stderr)]

    assert len(ran) == 1, ran
    assert f"add.{MARKER}.test.ts" in ran[0]


def test_acceptance_runs_the_changed_marked_file_only(workspace: Path) -> None:
    changed = [ADD_TEST, f"{CORE}/src/add.{MARKER}.test.ts"]
    commands = PROFILE.acceptance_commands(
        workspace, changed, marker=MARKER, exclude_marker="dev_stack", root_extras=[]
    )

    assert len(commands) == 1
    done = run(commands[0], workspace)
    assert done.returncode == 0, report(commands[0], done)
    ran = [t.test for t in PROFILE.parse_test_durations(done.stdout + done.stderr)]
    assert len(ran) == 1 and f"add.{MARKER}.test.ts" in ran[0], ran


def test_a_failing_test_in_one_member_fails_that_members_command_as_a_test_failure(
    workspace: Path,
) -> None:
    failing = (workspace / TOTAL_TEST).read_text().replace("toBe(6)", "toBe(7)")
    (member_command,) = PROFILE.test_commands(workspace, [TOTAL], root_extras=[])
    (other_command,) = PROFILE.test_commands(workspace, [ADD_TEST], root_extras=[])

    with seeded(workspace, TOTAL_TEST, failing):
        done = run(member_command, workspace)
        untouched = run(other_command, workspace)

    assert done.returncode != 0
    assert PROFILE.failure_kind(report(member_command, done)) == "test"
    assert [f.test for f in PROFILE.parse_test_failures(done.stdout + done.stderr)] != []
    assert untouched.returncode == 0, "the other member is not affected by the seeded failure"


def test_a_type_error_in_one_member_fails_the_type_check_as_a_types_failure(
    workspace: Path,
) -> None:
    (argv,) = PROFILE.project_checks(RepoConfig(path=workspace))

    with seeded(workspace, TOTAL, 'export const broken: number = "text";\n'):
        done = run(argv, workspace)

    assert done.returncode != 0
    assert PROFILE.failure_kind(report(argv, done)) == "types"


def test_an_unformatted_file_in_one_member_fails_lint_as_a_lint_failure(workspace: Path) -> None:
    argv = PROFILE.lint_command_all_files()

    with seeded(workspace, TOTAL, "export const   unformatted =   1\n"):
        done = run(argv, workspace)

    assert done.returncode != 0
    assert PROFILE.failure_kind(report(argv, done)) == "lint"
