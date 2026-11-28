"""Every shell-out the pipeline makes to git, in one place, and the one lookup
of a GitHub token from the `gh` login.

Nothing else runs `gh`: GitHub is reached over HTTP (`forges/github.py`), and
the credential a call carries is chosen per repo owner by `credential_source`.
A call against another account's private repo reports it as *nonexistent*,
which from the caller's side is indistinguishable from a repo with no PRs, so
the token is never left to whichever account is active.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from functools import cache
from pathlib import Path

from agent_build_kit.config import active
from agent_build_kit.forges.constants import GH_TOKEN_SOURCE
from agent_build_kit.path_discovery import checkout_root
from agent_build_kit.settings import settings


def repo_slug(repo: str) -> str:
    """The GitHub owner/name of a workspace repo, from abk.yaml."""
    try:
        return active().repos[repo].slug
    except KeyError:
        raise KeyError(
            f"{repo!r} is not a repo in the active workspace "
            f"(known: {', '.join(active().repos) or 'none'})"
        ) from None


# --- git ----------------------------------------------------------------------


def git(repo: Path, *args: str, check: bool = True, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=check, **kwargs
    )


def git_running_in(worktree: Path, proc: Path = Path("/proc")) -> bool:
    """Whether a git process is running with `worktree` as its working directory; `proc` is
    the process table, a parameter so a test can give it a fake one."""
    if not proc.is_dir():
        return True  # cannot tell, so assume one is
    here = worktree.resolve()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() != "git":
                continue
            cwd = (entry / "cwd").resolve()
        except OSError:
            continue
        if cwd == here or here in cwd.parents:
            return True
    return False


def is_tracked(root: Path, name: str) -> bool:
    return git(root, "ls-files", "--error-unmatch", name, check=False).returncode == 0


def tracked_toplevel(directory: Path, name: str) -> Path | None:
    """The top level of the git repository holding `directory` when git tracks `name` in it,
    None when `directory` is outside a repository or git does not track `name`."""
    top = checkout_root(directory)
    if top is None or not is_tracked(directory, name):
        return None
    return top


def is_ignored(root: Path, name: str) -> bool:
    return git(root, "check-ignore", "-q", name, check=False).returncode == 0


def git_out(repo: Path, *args: str) -> str:
    """stdout of a git command that must succeed, stripped."""
    return git(repo, *args).stdout.strip()


def commit_id(repo: Path, ref: str) -> str:
    """The full commit id `ref` names in `repo`, or empty when it names no commit."""
    try:
        found = git(repo, "rev-parse", "--verify", "-q", f"{ref}^{{commit}}", check=False)
    except OSError:  # the repository's folder is gone
        return ""
    return "" if found.returncode else found.stdout.strip()


def trunk_ref(checkout: Path, branch: str) -> str:
    """The ref to read a repo's trunk at: `origin/<branch>` when the checkout holds it (nothing
    is fetched), else the local `branch`."""
    return f"origin/{branch}" if commit_id(checkout, f"origin/{branch}") else branch


def changed_files(repo: Path, base: str) -> list[str]:
    """The paths the checked-out branch changes against `base` (`git diff base...HEAD`)."""
    result = git(repo, "diff", "--name-only", f"{base}...HEAD", check=False)
    return [line for line in result.stdout.splitlines() if line.strip()]


def fork_point(repo: Path, ref: str, head: str = "HEAD") -> str:
    """The commit where `head` (the checked-out branch unless named) left `ref`: the merge base
    of the two. An empty string when git cannot say, for a `ref` it cannot resolve or one that
    shares no history with `head`; a caller that wants `ref` itself then says `or ref`."""
    return git(repo, "merge-base", ref, head, check=False).stdout.strip()


def porcelain_entries(path: Path, *pathspec: str) -> list[tuple[str, str, str | None]]:
    """The checkout's changes as (status code, exact path, source), every untracked file named,
    limited to `pathspec` when given; the source is where a staged rename or copy came from, and
    None for any other change. Raises `CalledProcessError` where `path` is not under git."""
    args = ["status", "--porcelain", "-z", "--untracked-files=all"]
    fields = git(path, *args, *(("--", *pathspec) if pathspec else ())).stdout.split("\0")
    entries: list[tuple[str, str, str | None]] = []
    pending = iter(fields)
    for field in pending:
        if not field:
            continue
        code, name = field[:2], field[3:]
        # the source of a rename or copy follows as its own field
        source = (next(pending, "") or None) if "R" in code or "C" in code else None
        entries.append((code, name, source))
    return entries


def porcelain(path: Path, *pathspec: str) -> list[tuple[str, str]]:
    """The checkout's changes as (status code, exact path), every untracked file named, limited
    to `pathspec` when given. Raises `CalledProcessError` where `path` is not under git."""
    return [(code, name) for code, name, _ in porcelain_entries(path, *pathspec)]


def has_origin(repo: Path) -> bool:
    """Does the checkout have an `origin`? Only a repo git itself says has none is
    without one: a path git cannot read is left to fail where it is used."""
    if not repo.is_dir():
        return True
    remotes = git(repo, "remote", check=False)
    return bool(remotes.returncode) or "origin" in remotes.stdout.split()


# --- the gh login -------------------------------------------------------------


Run = Callable[..., subprocess.CompletedProcess]


def cli_token(owner: str, *, run: Run | None = None) -> str | None:
    """What `gh auth token --user <owner>` prints, or None when `gh` holds none.
    `run` stands in for subprocess.run."""
    result = (run or subprocess.run)(
        ["gh", "auth", "token", "--user", owner], capture_output=True, text=True, check=False
    )
    return (None if result.returncode else (result.stdout or "").strip()) or None


@cache
def token_for(owner: str) -> str | None:
    """The `gh` token for the account `owner`, or None when `gh` holds none."""
    return cli_token(owner)


def forget_tokens() -> None:
    """Forget the `gh` tokens read so far (after a re-login, and between tests)."""
    token_for.cache_clear()


def credential_source(owner: str, *, run: Run | None = None) -> tuple[str, str] | None:
    """The token calls for `owner`'s repos use, and where it came from.

    The one definition of the order: an explicitly configured token wins (one
    account may well have access to both repos, and saying so is simpler than
    inferring it), then the `gh` login for that owner. None when neither holds
    a token. A `run` reads the login afresh instead of through the cache.
    """
    if settings.gh_token:
        return settings.gh_token, GH_TOKEN_SOURCE
    token = token_for(owner) if run is None else cli_token(owner, run=run)
    return (token, f"gh auth token --user {owner}") if token else None
