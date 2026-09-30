"""The planning repo's default branch: which it is, and putting it back.

The pipeline reads and writes state there, and a track phase commits its
bookkeeping there, so both the tick and the tracks' runner start from — and
return to — that branch. One implementation, so the two cannot disagree about
a detached HEAD or a refused checkout.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.pipeline.shell import git


def is_repo(root: Path) -> bool:
    return git(root, "rev-parse", "--git-dir", check=False).returncode == 0


def default_branch_of(repo_dir: Path) -> str:
    """The branch `origin/HEAD` points at, or `main` when the checkout does
    not record one."""
    result = git(repo_dir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    if result.returncode != 0:
        return "main"
    return result.stdout.strip().removeprefix("origin/") or "main"


def restore_default_branch(root: Path, branch: str, say: Callable[[str], None]) -> bool:
    """Puts the planning repo back on `branch`, keeping any stray branch it was
    left on. False when it cannot be put back."""
    found = git(root, "symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
    if found == branch:
        return True
    where = found or "a detached HEAD"
    say(f"the planning repo was left on {where}, not {branch} — putting it back")
    if found:
        say(f"the branch {found} is kept")
    result = git(root, "checkout", branch, check=False)
    if result.returncode != 0:
        say(f"FATAL: cannot check out {branch} in {root}:\n{result.stderr}")
    return result.returncode == 0
