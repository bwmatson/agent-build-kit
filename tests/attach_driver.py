"""What the attachment tests share: a lease left by a process that has since exited, and a
unit's branch checked out in a real git worktree, where a chat leaves its changes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.workspaces import worktree_path
from tests.factories import git, init_repo

_LEAVE = (
    "import sys; from pathlib import Path; "
    "from agent_build_kit.pipeline.lease import Leases; "
    "directory, unit, holder, files, commit, *checkouts = sys.argv[1:]; "
    "leases = Leases(Path(directory)); "
    "assert leases.take(unit, holder, checkouts=tuple(checkouts), session='sess', "
    "runtime='claude_code', head='abc123'); "
    "int(files) and leases.mark_changes(unit, holder, int(files)); "
    "commit and leases.mark_committed(unit, holder, commit)"
)


def leave_lease(
    directory: Path,
    unit_id: str,
    holder: str = "tab:gone",
    *,
    files: int = 0,
    commit: str = "",
    checkouts: tuple[str, ...] = ("worktree",),
) -> None:
    """A lease its process has left behind by exiting, holding `files` changed files
    and, when `commit` is given, a commit made and not delivered."""
    subprocess.run(
        [sys.executable, "-c", _LEAVE, str(directory), unit_id, holder, str(files), commit]
        + list(checkouts),
        check=True,
    )


def checked_out(installation: Installation, unit_id: str) -> Path:
    """The unit's branch in a real worktree of the `app` checkout, with one commit on it."""
    unit = UnitStore(installation.state_dir / "units.json").get(unit_id)
    assert unit.branch
    repo = init_repo(installation.checkouts[unit.repo])
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "start")
    path = worktree_path(repo, unit.branch, installation.worktree_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-q", "-b", unit.branch, str(path))
    return path


def head(path: Path) -> str:
    return git(path, "rev-parse", "HEAD").strip()


def changed_files(path: Path) -> list[str]:
    return sorted(git(path, "ls-files", "--modified", "--others", "--exclude-standard").split())
