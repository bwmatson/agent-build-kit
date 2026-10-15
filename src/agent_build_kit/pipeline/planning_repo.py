"""The planning repo's default branch: which it is, and putting it back.

The pipeline reads and writes state there, and a track phase commits its
bookkeeping there, so both the tick and the tracks' runner start from — and
return to — that branch. One implementation, so the two cannot disagree about
a detached HEAD or a refused checkout.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git


def is_repo(root: Path) -> bool:
    return git(root, "rev-parse", "--git-dir", check=False).returncode == 0


def common_dir(path: Path) -> Path | None:
    """The common git directory of the repository `path` is in, the same for every worktree of
    it; None for a missing directory or one that is no repository."""
    if not path.is_dir():
        return None
    found = git(path, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False)
    return None if found.returncode else Path(found.stdout.strip()).resolve()


class RepositoryName(Frozen):
    name: str
    reason: str = ""


def main_working_tree(root: Path) -> Path | None:
    """The main working tree of the repository `root` is in, when its common git directory is
    named `.git`; None for a bare layout, a separate git directory or no repository."""
    common = common_dir(root)
    return common.parent if common is not None and common.name == ".git" else None


def repository_name(root: Path) -> RepositoryName:
    """What an installation in the repository `root` is in is called: the directory name of the
    repository's main working tree. When the common git directory is not named `.git`, the root's
    own directory name, with the reason `abk doctor` reports."""
    main = main_working_tree(root)
    if main is not None:
        return RepositoryName(name=main.name)
    common = common_dir(root)
    if common is None:
        return RepositoryName(name=root.name)
    return RepositoryName(
        name=root.name,
        reason=f"the common git directory {common} is not named .git, so {root.name} names it",
    )


def toplevel(path: Path) -> Path | None:
    """The top of the repository `path` is in, or of its nearest existing parent when `path` is
    not made yet; None when there is no repository."""
    here = path.resolve()
    while not here.is_dir() and here != here.parent:
        here = here.parent
    top = git(here, "rev-parse", "--show-toplevel", check=False)
    return Path(top.stdout.strip()).resolve() if top.returncode == 0 else None


def is_worktree_of(path: Path, common: Path) -> bool:
    """Whether `path` is the top of a worktree of the repository with this common git directory."""
    if not path.is_dir():
        return False
    return toplevel(path) == path.resolve() and common_dir(path) == common


def git_dir(path: Path) -> Path | None:
    """The git directory of the worktree `path` is in, which differs from `common_dir` for a
    linked worktree; None when `path` is in no repository."""
    found = git(path, "rev-parse", "--path-format=absolute", "--git-dir", check=False)
    return None if found.returncode else Path(found.stdout.strip()).resolve()


def current_branch(path: Path) -> str:
    """The short name of the branch `path` has checked out, or "" when HEAD is detached."""
    return git(path, "symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()


def repo_sharing(checkouts: Mapping[str, Path], path: Path) -> str | None:
    """The name of the checkout in the same repository as `path` (any worktree of it), else None."""
    here = common_dir(path)
    if here is None:
        return None
    return next(
        (name for name, checkout in checkouts.items() if common_dir(checkout) == here), None
    )


def default_branch_of(repo_dir: Path) -> str:
    """The branch `origin/HEAD` points at, or `main` when the checkout does
    not record one."""
    result = git(repo_dir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    if result.returncode != 0:
        return "main"
    return result.stdout.strip().removeprefix("origin/") or "main"


def detach_at(root: Path, commit: str, say: Callable[[str], None]) -> bool:
    """Puts a worktree left on a branch back, detached at `commit`, keeping the branch.
    False when it cannot be put back."""
    found = current_branch(root)
    if not found:
        return True
    say(f"the planning worktree was left on {found} — putting it back at {commit[:10]}")
    say(f"the branch {found} is kept")
    result = git(root, "checkout", "-q", "--detach", commit, check=False)
    if result.returncode != 0:
        say(f"FATAL: cannot detach HEAD in {root}:\n{result.stderr}")
    return result.returncode == 0


def restore_default_branch(root: Path, branch: str, say: Callable[[str], None]) -> bool:
    """Puts the planning repo back on `branch`, keeping any stray branch it was
    left on. False when it cannot be put back."""
    found = current_branch(root)
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
