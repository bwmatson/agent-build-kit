"""What the planning-commit tests share: a planning root that is a worktree of the repository it
lists (the in-repo shape), holding a change, a source file and a script standing in for the
OpenSpec command that records each time it runs."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.installation import Installation
from tests.conftest import make_installation
from tests.factories import commit_files, git, init_repo
from tests.planning_worktree_support import InRepo, in_repo, publish_elsewhere

CHANGE = "openspec/changes/feature/tasks.md"
SOURCE = "src/main.py"
NEW_SOURCE = "src/new.py"
TASKS = (
    "# Tasks\n\n## 1. [app] [unit-test] A group\n\nAcceptance: none — nothing to drive\n\n"
    "- [ ] 1.1 Test: it works\n"
)
EDITED_TASKS = TASKS.replace("A group", "A group, reworded")
START = {
    CHANGE: TASKS,
    SOURCE: "main\n",
    "abk.yaml": "repos: {}\n",
    "docs/unit_graph.md": "g\n",
    "runs/units.json": json.dumps({"units": []}) + "\n",
    ".gitignore": "runs/leases/\n",
}

_REPORT = json.dumps({"items": [], "summary": {"totals": {"items": 0, "passed": 0, "failed": 0}}})
_CHECK = f"""#!/bin/sh
echo run >> "$(dirname "$0")/openspec.runs"
echo '{_REPORT}'
"""


def recording_openspec(directory: Path) -> str:
    """The command that passes every check and writes a line to `openspec.runs` per run."""
    script = directory / "fake-openspec"
    script.write_text(_CHECK)
    script.chmod(0o755)
    return str(script)


def gate_runs(tmp_path: Path) -> int:
    runs = tmp_path / "setup" / "openspec.runs"
    return len(runs.read_text().split()) if runs.exists() else 0


def in_repo_planning(tmp_path: Path) -> tuple[Installation, InRepo]:
    """The pipeline worktree of `app` at the tip of `main`, holding `START`, as the root of an
    installation that lists `app` at the working copy."""
    base = tmp_path / "setup"
    setup = in_repo(base)
    publish_elsewhere(setup, START, "add planning and code")
    git(setup.worktree, "fetch", "-q", "origin")
    git(setup.worktree, "checkout", "-q", "--detach", "origin/main")
    git(setup.worktree, "config", "user.email", "t@t.t")
    git(setup.worktree, "config", "user.name", "t")
    inst = make_installation(
        setup.worktree,
        repos={"app": {"path": str(setup.working_copy), "slug": "example/app"}},
        planning={"worktree_root": str(base / "trees")},
        openspec={"command": [recording_openspec(base)]},
    )
    return inst, setup


def edit_change_and_source(root: Path) -> None:
    """A modified change, a modified source file and a new one."""
    (root / CHANGE).write_text(EDITED_TASKS)
    (root / SOURCE).write_text("edited\n")
    (root / NEW_SOURCE).write_text("new\n")


OUTSIDE = "notes/x.md"


def separate_planning(tmp_path: Path) -> Installation:
    """A planning repository of its own, holding `START`, whose installation lists `app` at a
    repository elsewhere: no listed repo shares the root's repository."""
    base = tmp_path / "setup"
    base.mkdir(parents=True, exist_ok=True)
    root = init_repo(base / "planning")
    commit_files(root, "add planning", START)
    commit_files(init_repo(base / "app"), "start", {"base.txt": "base\n"})
    return make_installation(
        root,
        repos={"app": {"path": str(base / "app"), "slug": "example/app"}},
        planning={"worktree_root": str(base / "trees")},
        openspec={"command": [recording_openspec(base)]},
    )
