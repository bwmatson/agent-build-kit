"""Stand-ins for the unit-test runner's toolchain and command runner, over a moved base.

The profile's `test_commands` is bound by assignment: a function named `test_*` defined in
a file under `tests/` is read as a test the unit added."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.factories import git, init_repo

BASE_FILES = {"a.py": "a = 1\n", "b.py": "b = 1\n", "c.py": "c = 1\n"}


def one_test_command(
    self: PythonUvProfile,
    repo: Path,
    changed: list[str],
    *,
    root_extras: list[str],
    **_workers: object,
) -> list[list[str]]:
    return [["tests"]]


class Profile(PythonUvProfile):
    """The python-uv profile running one lint command and one test command."""

    def lint_command(self, base: str) -> list[str]:
        return ["lint"]

    test_commands = one_test_command


def passing(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "5 passed\n", "")


def commit(repo: Path, files: dict[str, str], message: str) -> None:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message, "--allow-empty")


def affected_lines(workspace: Installation) -> list[dict]:
    path = workspace.state_dir / "usage-ledger.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [line for line in lines if line.get("kind") == "affected"]


def moved(
    tmp_path: Path,
    *,
    own: dict[str, str],
    incoming: dict[str, str],
    at: Path | None = None,
    base: dict[str, str] | None = None,
) -> tuple[Path, str]:
    """A repo whose branch changes `own` and whose `main` moved on by `incoming`, the
    branch replayed onto it. Returns the repo, on the branch, and the old base."""
    repo = init_repo(at or tmp_path / "repo")
    commit(repo, BASE_FILES if base is None else base, "base")
    old_base = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "checkout", "-q", "-b", "spec/feature/1")
    commit(repo, own, "unit")
    git(repo, "checkout", "-q", "main")
    commit(repo, incoming, "main moves")
    git(repo, "checkout", "-q", "spec/feature/1")
    git(repo, "rebase", "-q", "main")
    return repo, old_base
