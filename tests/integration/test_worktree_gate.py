"""The environment a build runs in: a git worktree, under the repository's own
pre-commit gate.

A build does not run in a checkout. It runs in a worktree off the repo, on a
branch named for the unit, with the repo's pre-commit hooks between it and every
commit. A checker that is configured well for a checkout can match no files at
all there, and the only symptom is a unit whose commit is rejected with nothing
wrong in its code. This puts one trivially correct file through that gate.

Needs the network on a first run, to install the hooks' environments. That first
run installs them into the test's empty home, so the test carries the loaded
time limit.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from agent_build_kit.pipeline.shell import git as run_git
from tests.factories import git, init_repo
from tests.time_limit import LOADED_TEST_TIME_LIMIT

pytestmark = [
    pytest.mark.integration,
    pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT),
]

REPO = Path(__file__).resolve().parents[2]

# What the repository's gate is made of: its hooks and the tool settings they read.
GATE_FILES = (
    ".pre-commit-config.yaml",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    ".yamllint",
    ".gitignore",
)

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


def _build_paths(project_dir: Path) -> list[str]:
    """The source paths the project's hatch build names: each target's forced
    includes (the source side) and packages, relative to the project's folder."""
    project = tomllib.loads((project_dir / "pyproject.toml").read_text())
    targets = project.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {})
    paths: list[str] = []
    for target in targets.values():
        paths.extend(target.get("force-include", {}))
        paths.extend(target.get("packages", []))
    return paths


def _create_layout(repo: Path, relative_dir: Path) -> None:
    """Create the folders the copied project at `relative_dir` builds from, and,
    for each uv workspace member it lists, copy the member's project file from
    this repository and do the same for it."""
    for path in _build_paths(repo / relative_dir):
        target = repo / relative_dir / path
        if target.exists():
            continue
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("")
        else:
            target.mkdir(parents=True)
            (target / "__init__.py").write_text("")
    project = tomllib.loads((repo / relative_dir / "pyproject.toml").read_text())
    members = project.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])
    for pattern in members:
        for source in sorted((REPO / relative_dir).glob(pattern)):
            member = relative_dir / source.relative_to(REPO / relative_dir)
            if not (source / "pyproject.toml").is_file():
                continue
            (repo / member).mkdir(parents=True, exist_ok=True)
            shutil.copy(source / "pyproject.toml", repo / member / "pyproject.toml")
            _create_layout(repo, member)


def _worktree_of_a_fixture_repo(tmp_path: Path) -> Path:
    """A fixture repo carrying this repository's own gate, with its hooks
    installed, and a worktree of it on a unit's branch — where builds run."""
    repo = init_repo(tmp_path / "app")
    for name in GATE_FILES:
        shutil.copy(REPO / name, repo / name)
    (repo / "src" / "probe").mkdir(parents=True)
    # The hooks run the lock's tools through `uv run --frozen`, which builds the
    # project the lock describes; this is the package pyproject.toml names.
    (repo / "src" / "agent_build_kit").mkdir()
    (repo / "src" / "agent_build_kit" / "__init__.py").write_text("")
    (repo / "src" / "probe" / "__init__.py").write_text("")
    # On a branch where the kit is a uv workspace the copied project names more
    # folders than that; build whatever it names.
    _create_layout(repo, Path())
    (repo / "tests").mkdir()
    (repo / "tests" / ".keep").write_text("")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    subprocess.run(
        [sys.executable, "-m", "pre_commit", "install"], cwd=repo, check=True, capture_output=True
    )

    tree = tmp_path / "worktree"
    git(repo, "worktree", "add", "-q", "-b", "spec/probe/1", str(tree))
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
