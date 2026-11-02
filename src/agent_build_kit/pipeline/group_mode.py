"""How a task group is built: the mode every check, route and prompt of a build follows."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum


class GroupMode(StrEnum):
    """How a group is built: tests first then code, tests only, no code at all (documents or
    configuration), or a reorganization (a lone code commit with no new test)."""

    TESTS_AND_CODE = "tests_and_code"
    TESTS_ONLY = "tests_only"
    NO_CODE = "no_code"
    REFACTOR = "refactor"

    @property
    def writes_tests(self) -> bool:
        """Whether the build has a tests step for the group."""
        return self in (GroupMode.TESTS_AND_CODE, GroupMode.TESTS_ONLY)

    @property
    def writes_code(self) -> bool:
        """Whether the build has an implementation step for the group."""
        return self is not GroupMode.TESTS_ONLY

    @property
    def accepts_tests_commit(self) -> bool:
        """Whether a `test:` commit of the group's title is one the group takes: every mode
        but `refactor` does (for `no_code` it is the optional one)."""
        return self is not GroupMode.REFACTOR

    @property
    def tests_first(self) -> bool:
        """Whether the group's tests are committed first and seen to fail (the red check)."""
        return self is GroupMode.TESTS_AND_CODE


def mode_of_flag(flag: bool | GroupMode) -> GroupMode:
    """A mode, given one or the earlier `test_only` flag in its place."""
    if isinstance(flag, GroupMode):
        return flag
    return GroupMode.TESTS_ONLY if flag else GroupMode.TESTS_AND_CODE


def modes_of(flags: Sequence[bool | GroupMode]) -> list[GroupMode]:
    """Each of `flags` as a mode."""
    return [mode_of_flag(flag) for flag in flags]
