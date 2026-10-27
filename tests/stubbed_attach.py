"""What the tests of `abk attach release --commit` over a stubbed unit share: an installation whose
unit `feature/2` is built in stubbed groups, its branch in a real worktree, and the chat's
uncommitted files left under a lease whose server has gone."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.commit_order import branch_subjects, group_progress
from agent_build_kit.pipeline.lease import lease_dir
from tests.attach_driver import checked_out, leave_lease
from tests.conftest import make_installation
from tests.factories import git
from tests.serving import seed_pipeline

UNIT = "feature/2"
TITLE = "Add the marker"


def stubbed_installation(tmp_path: Path) -> Installation:
    """An installation whose builds are stubbed, with the seeded units and the tasks file of
    `feature`, whose one group is titled `TITLE`."""
    installation = make_installation(
        tmp_path / "planning",
        planning={"worktree_root": str(tmp_path / "worktrees")},
        builders={"stubbed_tdd_commits": True},
    )
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    seed_pipeline(installation)
    tasks = installation.changes_dir / "feature" / "tasks.md"
    tasks.parent.mkdir(parents=True, exist_ok=True)
    tasks.write_text(f"## 1. [app] [unit-test] {TITLE}\n\n- [ ] 1.1 Test: it\n- [ ] 1.2 Do it\n")
    return installation


def dirty_tree(installation: Installation, *subjects: str) -> Path:
    """The unit's worktree holding an edit and a new file under an abandoned lease, on a branch
    that carries an empty commit for each of `subjects`, oldest first."""
    path = checked_out(installation, UNIT)
    for subject in subjects:
        git(path, "commit", "-q", "--allow-empty", "-m", subject)
    (path / "base.txt").write_text("edited by a chat\n")
    (path / "new.py").write_text("NEW = 1\n")
    leave_lease(lease_dir(installation.state_dir), UNIT, files=2)
    return path


def last_subject(tree: Path) -> str:
    return git(tree, "log", "-1", "--format=%s").strip()


def last_body(tree: Path) -> str:
    return git(tree, "log", "-1", "--format=%b").strip()


def groups_paired(tree: Path, titles: list[str]) -> int:
    """How many of the groups titled `titles` the branch beyond its first commit has a pair
    for, as the build counts them."""
    start = git(tree, "rev-list", "--max-parents=0", "HEAD").strip()
    return group_progress(branch_subjects(tree, start), titles).done
