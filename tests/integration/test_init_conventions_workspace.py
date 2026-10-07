"""`abk init` over a scratch workspace: what it leaves in each code repo.

`abk init` is the real CLI run as a process against three scratch code repos, one
with an `AGENTS.md`, one with only a `CLAUDE.md` and one with neither, and a
scratch planning directory. Research and proposals are skipped, so no agent is
needed; the OpenSpec CLI is real. The repos are read back the way a person would
read them: their files and `git status`.

Needs node for the OpenSpec CLI. Marked tier 2 and excluded from the default suite;
run it with `uv run pytest -m local_stack tests/integration/test_init_conventions_workspace.py`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.factories import git, init_repo

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
]

AGENTS = "# App\n\nBuild it with care.\n"
CLAUDE = "# Platform\n\nSee the docs.\n"
BLOCK_OPEN = "<!-- abk:changelog v"
BLOCK_CLOSE = "<!-- /abk:changelog -->"
RULE = "CHANGELOG.md merge=union"


def code_repo(tmp_path: Path, name: str, **files: str) -> Path:
    root = init_repo(tmp_path / name)
    git(root, "remote", "add", "origin", f"git@github.com:example/{name}.git")
    (root / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')
    for relative, content in files.items():
        (root / relative).write_text(content)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "code")
    return root


def run_init(planning: Path, repos: list[Path]) -> subprocess.CompletedProcess[str]:
    argv = [str(Path(sys.executable).parent / "abk"), "init", str(planning)]
    for root in repos:
        argv += ["--repo", str(root)]
    argv += ["--yes", "--skip-research", "--skip-propose"]
    env = {k: v for k, v in os.environ.items() if k != "ABK_CONFIG"}
    return subprocess.run(argv, capture_output=True, text=True, env=env, check=False, timeout=300)


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


def test_init_leaves_each_repo_as_the_spec_says_and_a_second_run_changes_nothing(
    tmp_path: Path,
) -> None:
    planning = tmp_path / "planning"
    app = code_repo(tmp_path, "app", **{"AGENTS.md": AGENTS})
    platform = code_repo(tmp_path, "platform", **{"CLAUDE.md": CLAUDE})
    worker = code_repo(tmp_path, "worker")
    repos = [app, platform, worker]

    first = run_init(planning, repos)

    assert first.returncode == 0, first.stdout + first.stderr
    for root in repos:
        assert (root / "CHANGELOG.md").read_text() == "# Changelog\n\n## Unreleased\n"
        assert (root / ".gitattributes").read_text() == f"{RULE}\n"
    agents = (app / "AGENTS.md").read_text()
    assert agents.startswith(AGENTS)
    assert BLOCK_OPEN in agents and agents.rstrip().endswith(BLOCK_CLOSE)
    assert not (app / "CLAUDE.md").exists()
    claude = (platform / "CLAUDE.md").read_text()
    assert claude.startswith(CLAUDE)
    assert BLOCK_OPEN in claude and claude.rstrip().endswith(BLOCK_CLOSE)
    assert not (platform / "AGENTS.md").exists()
    created = (worker / "AGENTS.md").read_text()
    assert created.lstrip().startswith(BLOCK_OPEN) and created.rstrip().endswith(BLOCK_CLOSE)
    assert not (worker / "CLAUDE.md").exists()
    for root in repos:
        assert len(git(root, "log", "--oneline").splitlines()) == 1, "nothing is committed"
        assert git(root, "status", "--porcelain"), "the changes are left in the working tree"

    before = {root: snapshot(root) for root in repos}
    status = {root: git(root, "status", "--porcelain") for root in repos}

    second = run_init(planning, repos)

    assert second.returncode == 0, second.stdout + second.stderr
    for root in repos:
        assert snapshot(root) == before[root]
        assert git(root, "status", "--porcelain") == status[root]
    lines = [
        line
        for line in second.stdout.splitlines()
        if line.lstrip().startswith(("app/", "platform/", "worker/"))
    ]
    assert len(lines) == 9, second.stdout
    assert all(line.endswith("already current") for line in lines), second.stdout
