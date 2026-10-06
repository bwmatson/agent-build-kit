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


def git_out(repo: Path, *args: str) -> str:
    """stdout of a git command that must succeed, stripped."""
    return git(repo, *args).stdout.strip()


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
