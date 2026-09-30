"""Every shell-out the pipeline makes to git and gh, in one place.

There were twelve private wrappers across the package — five `_git`, four `_gh`
and a `_run` that special-cased gh — and the repetition was not the problem.
The problem was what each `gh` copy had to remember: the two code repos live on
two GitHub accounts, `gh` has one active account at a time, and a call against
the other account's private repo reports it as *nonexistent*. From the caller's
side that is indistinguishable from a repo with no PRs, so the poller can run
clean while seeing nothing of one repo at all.

So `gh()` always selects the token for the repo it names, and there is no way
to call gh here without it. A new call site cannot forget, because there is no
second way to write one.
"""

from __future__ import annotations

import json
import os
import subprocess
from functools import cache
from pathlib import Path

from agent_build_kit.config import active
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


# --- gh -----------------------------------------------------------------------


@cache
def token_for(owner: str) -> str | None:
    """The `gh` token for the account `owner`, or None when `gh` holds none."""
    result = subprocess.run(
        ["gh", "auth", "token", "--user", owner], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or None


def gh_env(slug: str) -> dict[str, str]:
    """The environment a `gh` call against `slug` needs.

    Selecting the token per owner rather than switching the active account
    keeps it stateless, which matters because units run concurrently.
    """
    # An explicitly configured token wins: one account may well have access to
    # both repos, and saying so is simpler than inferring it.
    token = settings.gh_token or token_for(slug.split("/")[0])
    # The whole environment, not just the token: `gh` needs PATH and HOME, and
    # a partial env is the kind of thing that works until it runs under systemd.
    return {**os.environ, "GH_TOKEN": token} if token else dict(os.environ)


def slug_in(args: list[str]) -> str:
    """The `--repo owner/name` a gh command names, if it names one."""
    for flag, value in zip(args, args[1:], strict=False):
        if flag == "--repo":
            return value
    return ""


def gh(args: list[str], *, slug: str = "", **kwargs) -> subprocess.CompletedProcess[str]:
    """Run gh as the account that owns the repo, never raising on exit status.

    `slug` is for commands that name their repo in a path rather than with
    `--repo` — `gh api repos/<owner>/<name>/...`.
    """
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        env=gh_env(slug or slug_in(args)),
        **kwargs,
    )


class GhError(RuntimeError):
    """A gh command that failed. `stderr` is the host's answer alone: the
    message also carries the command line, which can hold a title or body."""

    def __init__(self, message: str, *, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


def gh_out(args: list[str], *, slug: str = "") -> str:
    """stdout of a gh command that must succeed, or GhError naming why."""
    result = gh(args, slug=slug)
    if result.returncode:
        detail = result.stderr.strip()
        raise GhError(f"{' '.join(args)} failed: {detail}", stderr=detail)
    return result.stdout


def gh_json(args: list[str], *, slug: str = "", default: object = None) -> object:
    """Parsed JSON from gh, or `default` if the call or the parse failed.

    For reads where "could not tell" and "nothing there" lead to the same
    action. Callers that must distinguish them use `gh_out`.
    """
    fallback = [] if default is None else default
    result = gh(args, slug=slug)
    if result.returncode:
        return fallback
    try:
        return json.loads(result.stdout or "null") or fallback
    except ValueError:
        return fallback
