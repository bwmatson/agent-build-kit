"""The node-npm type check follows the project's own `typecheck` script, and a failure is
classified by the command that failed (spec: node-npm-lint-and-test).

The clean check runs for real with `npm` and `npx` replaced by programs that record the call
they were given; the project check and the classification are read from the argv and the
`$ command (exit N)` header the pipeline puts above a failed command's output.
"""

from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import RepoConfig
from tests.node_runtime import require_node

# These run the profile's script probe against a real `node`, which `require_node` finds or skips.
pytestmark = pytest.mark.real_node_tool

SCRIPT_TYPES = ["npm", "run", "typecheck"]
GENERIC_TYPES = ["npx", "tsc", "--noEmit"]

RECORDER = """\
#!/bin/sh
echo "$(basename "$0") $*" >> "$CALLS"
exit 0
"""

# Each kind of project: its `scripts` and the type-check command it gets.
TYPE_CHECKS: dict[str, tuple[dict[str, str] | None, list[str]]] = {
    "typecheck script": ({"typecheck": "tsc -p tsconfig.app.json --noEmit"}, SCRIPT_TYPES),
    "other scripts": ({"lint": "oxlint src", "build": "tsc"}, GENERIC_TYPES),
    "no scripts field": (None, GENERIC_TYPES),
}


@pytest.fixture
def profile():
    return profiles.get("node-npm")


@pytest.fixture
def calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The file the recording `npm` and `npx`, first on the path, append their calls to."""
    require_node()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("npm", "npx"):
        program = bin_dir / name
        program.write_text(RECORDER)
        program.chmod(program.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("CALLS", str(log))
    return log


def project_with(scripts: dict[str, str] | None, where: Path) -> Path:
    """A project folder at `where` whose `package.json` has `scripts` (no field when None)."""
    where.mkdir()
    manifest: dict[str, object] = {"name": "app", "version": "1.0.0"}
    if scripts is not None:
        manifest["scripts"] = scripts
    (where / "package.json").write_text(json.dumps(manifest))
    return where


def failure(command: list[str], code: int = 1) -> str:
    return f"$ {shlex.join(command)} (exit {code})\n(in /work/project)\nerror: it failed\n"


def run_project_check(profile, repo: Path, where: Path) -> tuple[list[str], list[str]]:
    """The project check of `repo`, run in `where`: the command and the calls it made."""
    (command,) = profile.project_checks(RepoConfig(path=repo))
    done = subprocess.run(command, cwd=where, capture_output=True)
    assert done.returncode == 0
    return command, Path(os.environ["CALLS"]).read_text().splitlines()


def test_the_project_check_is_the_typecheck_script_when_the_project_defines_it(
    profile, tmp_path: Path, calls: Path
) -> None:
    ran = {}
    for kind, (scripts, _) in TYPE_CHECKS.items():
        project = project_with(scripts, tmp_path / kind.replace(" ", "-"))
        calls.write_text("")
        ran[kind] = run_project_check(profile, project, project)[1]

    assert ran == {kind: [" ".join(expected)] for kind, (_, expected) in TYPE_CHECKS.items()}


@pytest.mark.parametrize(
    ("root_scripts", "project_scripts", "expected"),
    [
        (None, {"typecheck": "tsc -p tsconfig.app.json --noEmit"}, SCRIPT_TYPES),
        ({"typecheck": "tsc --noEmit"}, {"build": "tsc"}, GENERIC_TYPES),
    ],
    ids=["only the project defines it", "only the checkout root defines it"],
)
def test_the_project_check_reads_the_manifest_of_the_folder_it_runs_in(
    profile,
    tmp_path: Path,
    calls: Path,
    root_scripts: dict[str, str] | None,
    project_scripts: dict[str, str],
    expected: list[str],
) -> None:
    root = project_with(root_scripts, tmp_path / "repo")
    project = project_with(project_scripts, root / "web")

    command, recorded = run_project_check(profile, root, project)

    assert recorded == [" ".join(expected)]
    assert profile.failure_kind(failure(command)) == "types"


def test_the_typecheck_script_is_found_whatever_the_manifest_looks_like(
    profile, tmp_path: Path, calls: Path
) -> None:
    pretty = tmp_path / "pretty"
    pretty.mkdir()
    # npm's own layout: a script with braces comes before the ones the gate follows.
    scripts = {
        "format": 'prettier --write "src/**/*.{ts,tsx}"',
        "lint": "eslint src",
        "format:check": "prettier --check src",
        "typecheck": "tsc -p tsconfig.app.json --noEmit",
    }
    (pretty / "package.json").write_text(json.dumps({"scripts": scripts}, indent=2))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "package.json").write_text(
        json.dumps({"scripts": {"build": "tsc"}, "other": {"typecheck": "x"}})
    )

    pretty_calls = []
    for where in (pretty, elsewhere):
        calls.write_text("")
        subprocess.run(
            ["sh", "-c", profile.clean_command(types=True)], cwd=where, capture_output=True
        )
        pretty_calls.append(calls.read_text().splitlines())

    assert pretty_calls == [
        ["npm run lint", "npm run format:check", "npm run typecheck"],
        ["npx oxlint .", "npx oxfmt --check .", "npx tsc --noEmit"],
    ]


def test_the_clean_check_with_types_ends_with_the_projects_type_check(
    profile, tmp_path: Path, calls: Path
) -> None:
    last_calls = {}
    for kind, (scripts, _) in TYPE_CHECKS.items():
        project = project_with(scripts, tmp_path / kind.replace(" ", "-"))
        calls.write_text("")
        done = subprocess.run(
            ["sh", "-c", profile.clean_command(types=True)], cwd=project, capture_output=True
        )
        assert done.returncode == 0
        last_calls[kind] = calls.read_text().splitlines()[-1]

    assert last_calls == {kind: " ".join(expected) for kind, (_, expected) in TYPE_CHECKS.items()}


def test_the_clean_check_runs_the_type_check_script_only_when_types_are_asked_for(
    profile, tmp_path: Path, calls: Path
) -> None:
    project = project_with({"typecheck": "tsc --noEmit"}, tmp_path / "project")

    subprocess.run(["sh", "-c", profile.clean_command()], cwd=project, capture_output=True)
    without_types = calls.read_text()
    calls.write_text("")
    subprocess.run(
        ["sh", "-c", profile.clean_command(types=True)], cwd=project, capture_output=True
    )
    with_types = calls.read_text()

    assert "typecheck" not in without_types
    assert "tsc" not in without_types
    assert "typecheck" in with_types


def test_a_failure_is_classified_by_the_command_that_failed(profile) -> None:
    commands = [
        SCRIPT_TYPES,
        GENERIC_TYPES,
        ["npm", "run", "lint"],
        ["npm", "run", "format:check"],
        ["npx", "oxlint", "."],
    ]

    kinds = {shlex.join(command): profile.failure_kind(failure(command)) for command in commands}

    assert kinds == {
        "npm run typecheck": "types",
        "npx tsc --noEmit": "types",
        "npm run lint": "lint",
        "npm run format:check": "lint",
        "npx oxlint .": "lint",
    }
