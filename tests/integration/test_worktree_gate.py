"""The environment a build runs in: a git worktree, under the repository's own
pre-commit gate.

A build does not run in a checkout. It runs in a worktree off the repo, on a
branch named for the unit, with the repo's pre-commit hooks between it and every
commit. A checker that is configured well for a checkout can match no files at
all there, and the only symptom is a unit whose commit is rejected with nothing
wrong in its code. This puts one trivially correct file through that gate.

Needs the network on a first run, to install the hooks' environments.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit.pipeline.shell import git as run_git
from tests.factories import git, init_repo

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]

# What the repository's gate is made of: its hooks and the tool settings they read.
GATE_FILES = (".pre-commit-config.yaml", "pyproject.toml", ".yamllint", ".gitignore")

# Formatted differently from how ruff-format writes it, and correct otherwise: the
# formatter must change it, and the linter and type checker then read the result.
UNFORMATTED = "def probe( ) -> dict[str, int]:\n    return  {'answer':42}\n"

HOOK_LINE = re.compile(r"^(?P<name>.+?)\.{2,}(?P<note>\(.*\))?(?P<status>Passed|Failed|Skipped)$")


def _hooks(output: str) -> dict[str, tuple[str, str]]:
    """Each hook's name against its status and note, as pre-commit printed them."""
    found: dict[str, tuple[str, str]] = {}
    for line in output.splitlines():
        if match := HOOK_LINE.match(line.strip()):
            found[match["name"].strip()] = (match["status"], match["note"] or "")
    return found


def _worktree_of_a_fixture_repo(tmp_path: Path) -> Path:
    """A fixture repo carrying this repository's own gate, with its hooks
    installed, and a worktree of it on a unit's branch — where builds run."""
    repo = init_repo(tmp_path / "app")
    for name in GATE_FILES:
        shutil.copy(REPO / name, repo / name)
    (repo / "src" / "probe").mkdir(parents=True)
    (repo / "src" / "probe" / "__init__.py").write_text("")
    (repo / "tests").mkdir()
    (repo / "tests" / ".keep").write_text("")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    subprocess.run(
        [sys.executable, "-m", "pre_commit", "install"], cwd=repo, check=True, capture_output=True
    )

    tree = tmp_path / "worktree"
    git(repo, "worktree", "add", "-q", "-b", "spec/probe/1", str(tree))
    # The gate points pyrefly at the repo's own interpreter; a build has synced
    # one into its worktree, and this stands for it.
    (tree / ".venv").symlink_to(sys.prefix, target_is_directory=True)
    return tree


def test_a_trivially_correct_file_is_committed_in_a_worktree_through_the_real_gate(
    tmp_path: Path,
) -> None:
    tree = _worktree_of_a_fixture_repo(tmp_path)
    (tree / "src" / "probe" / "probe.py").write_text(UNFORMATTED)

    # A hook that rewrites a file rejects the commit it ran under; the build's
    # own next step is to stage the rewrite and commit again, so this does too.
    # What the second attempt says is the verdict: a linter that objects to
    # what the formatter just wrote fails it.
    attempts = []
    for _ in range(2):
        git(tree, "add", "-A")
        attempt = run_git(tree, "commit", "-qm", "probe", check=False)
        attempts.append(attempt.stdout + attempt.stderr)
        if attempt.returncode == 0:
            break
    output = attempts[-1]
    hooks = _hooks(output)

    failed = sorted(name for name, (status, _) in hooks.items() if status == "Failed")
    unseen = sorted(
        name
        for name, (status, note) in hooks.items()
        if status == "Skipped" and re.search(r"ruff|pyrefly", name, re.I)
    )
    assert not unseen, (
        f"hook(s) {unseen} matched none of the files in the worktree, so they checked nothing:\n"
        f"{output}"
    )
    assert not failed, f"hook(s) {failed} rejected a trivially correct commit:\n{output}"
    assert attempts and git(tree, "log", "-1", "--format=%s").strip() == "probe", output
