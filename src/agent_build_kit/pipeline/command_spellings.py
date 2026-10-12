"""The spellings of each forbidden command class, listed once.

The judge's tests and the policy check's probe both read `SPELLINGS`, so the
rules and the check cannot drift: a spelling added here is tested and probed
with no second edit.
"""

from __future__ import annotations

from enum import StrEnum

from agent_build_kit.model import Frozen


class SpellingName(StrEnum):
    PLAIN = "plain"
    DIRECTORY = "directory"
    CONFIG = "config"
    NO_PAGER = "no-pager"
    GIT_DIR = "git-dir"
    WORK_TREE = "work-tree"
    COMBINED = "combined"
    GIT_DIR_SEPARATE = "git-dir-separate"
    WORK_TREE_SEPARATE = "work-tree-separate"
    REFSPEC = "refspec"
    MASTER = "master"
    REPO = "repo"
    REPO_LONG = "repo-long"
    REPO_EQUALS = "repo-equals"
    API_PUT = "api-put"
    API_METHOD_AFTER = "api-method-after"
    API_METHOD = "api-method"
    API_QUERY = "api-query"
    API_TRAILING_SLASH = "api-trailing-slash"
    ENV = "env"
    COMMAND = "command"
    SUDO = "sudo"
    SUDO_USER = "sudo-user"
    DIRECTORY_CHANGE = "directory-change"


class Reader(StrEnum):
    """Who reads a row: the judge's tests, the policy check's probe, or both."""

    JUDGE = "judge"
    PROBE = "probe"
    GLOB = "glob"


class Spelling(Frozen):
    name: SpellingName
    command: str
    readers: frozenset[Reader] = frozenset({Reader.JUDGE, Reader.PROBE})


JUDGE = frozenset({Reader.JUDGE})

# The global-option spellings of a git command, as the prefix before its
# subcommand, in the order the probe attempts them.
GIT_PREFIXES = (
    (SpellingName.PLAIN, "git"),
    (SpellingName.DIRECTORY, "git -C ."),
    (SpellingName.CONFIG, "git -c core.editor=true"),
    (SpellingName.NO_PAGER, "git --no-pager"),
    (SpellingName.GIT_DIR, "git --git-dir=.git"),
    (SpellingName.WORK_TREE, "git --work-tree=."),
    (SpellingName.COMBINED, "git -C . -c k=v --no-pager"),
)

AMEND = "commit --amend --no-edit"
MERGE = "gh -R o/r pr merge 1"


def _git(tail: str) -> tuple[Spelling, ...]:
    return tuple(Spelling(name=name, command=f"{prefix} {tail}") for name, prefix in GIT_PREFIXES)


def _wrapped(command: str) -> tuple[Spelling, ...]:
    """The wrapper and directory-change prefixes in front of `command`: read by
    the judge alone, since the agent folds a wrapper's name before matching."""
    return tuple(
        Spelling(name=name, command=f"{prefix}{command}", readers=JUDGE)
        for name, prefix in (
            (SpellingName.ENV, "env X=1 "),
            (SpellingName.COMMAND, "command "),
            (SpellingName.SUDO, "sudo "),
            (SpellingName.SUDO_USER, "sudo -u root "),
            (SpellingName.DIRECTORY_CHANGE, "cd . ; "),
        )
    )


# Forbidden class (in abk's words, as the probe's report names it) to its
# spellings, in the order the probe attempts them.
SPELLINGS: dict[str, tuple[Spelling, ...]] = {
    "amending a commit": (
        *_git(AMEND),
        Spelling(
            name=SpellingName.GIT_DIR_SEPARATE,
            command=f"git --git-dir .git {AMEND}",
            readers=JUDGE,
        ),
        Spelling(
            name=SpellingName.WORK_TREE_SEPARATE,
            command=f"git --work-tree . {AMEND}",
            readers=JUDGE,
        ),
        *_wrapped(f"git -C . {AMEND}"),
    ),
    "pushing to the default branch": (
        *_git("push origin main"),
        Spelling(
            name=SpellingName.REFSPEC,
            command="git --no-pager push origin HEAD:main",
            readers=JUDGE,
        ),
        Spelling(name=SpellingName.MASTER, command="git -C . push origin master", readers=JUDGE),
    ),
    "a force push to the default branch": _git("push --force origin +main"),
    "merging a pull request": (
        Spelling(name=SpellingName.PLAIN, command="gh pr merge 1"),
        Spelling(name=SpellingName.REPO, command=MERGE),
        Spelling(name=SpellingName.REPO_LONG, command="gh --repo o/r pr merge 1"),
        Spelling(name=SpellingName.REPO_EQUALS, command="gh --repo=o/r pr merge 1", readers=JUDGE),
        *_wrapped(MERGE),
    ),
    "merging a pull request through the host's raw API": (
        Spelling(name=SpellingName.API_PUT, command="gh api -X PUT repos/o/r/pulls/1/merge"),
        Spelling(
            name=SpellingName.API_METHOD_AFTER,
            command="gh api repos/o/r/pulls/1/merge -X PUT",
        ),
        Spelling(
            name=SpellingName.API_METHOD,
            command="gh api --method PUT repos/o/r/pulls/1/merge",
            readers=JUDGE,
        ),
        Spelling(
            name=SpellingName.API_QUERY,
            command="gh api -X PUT repos/o/r/pulls/1/merge?merge_method=squash",
            readers=JUDGE,
        ),
        Spelling(
            name=SpellingName.API_TRAILING_SLASH,
            command="gh api repos/o/r/pulls/1/merge/ -X PUT",
            readers=JUDGE,
        ),
    ),
    "a hard reset": (
        Spelling(name=SpellingName.DIRECTORY, command="git -C . reset --hard", readers=JUDGE),
    ),
    "force-deleting a branch": (
        Spelling(name=SpellingName.DIRECTORY, command="git -C . branch -D x", readers=JUDGE),
    ),
}


def probe_rows() -> list[tuple[str, Spelling]]:
    """The rows the policy check's probe attempts, as (class, spelling), in table order."""
    return [
        (label, spelling)
        for label, spellings in SPELLINGS.items()
        for spelling in spellings
        if Reader.PROBE in spelling.readers
    ]
