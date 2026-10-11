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
    API_PUT = "api-put"
    API_METHOD_AFTER = "api-method-after"
    API_METHOD = "api-method"
    ENV = "env"
    COMMAND = "command"
    SUDO = "sudo"
    SUDO_USER = "sudo-user"
    DIRECTORY_CHANGE = "directory-change"


class Reader(StrEnum):
    """Who reads a row: the judge's tests, the policy check's probe, or both."""

    JUDGE = "judge"
    PROBE = "probe"


class Spelling(Frozen):
    name: SpellingName
    command: str
    readers: frozenset[Reader] = frozenset({Reader.JUDGE, Reader.PROBE})


# Forbidden class (in abk's words, as the probe's report names it) to its
# spellings, in the order the probe attempts them.
SPELLINGS: dict[str, tuple[Spelling, ...]] = {}
