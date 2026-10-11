"""The table of spellings, as the judge's tests read it.

A test loops over a class's rows and reports the ones the rules got wrong, so
one failure names every spelling at fault rather than the first.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.pipeline.command_spellings import SPELLINGS, Reader, Spelling, SpellingName
from agent_build_kit.runtimes.acp import probe_branch

WRAPPERS = {
    SpellingName.ENV,
    SpellingName.COMMAND,
    SpellingName.SUDO,
    SpellingName.SUDO_USER,
    SpellingName.DIRECTORY_CHANGE,
}

AMEND = "amending a commit"
PUSH = "pushing to the default branch"
FORCE_PUSH = "a force push to the default branch"
MERGE = "merging a pull request"
RAW_MERGE = "merging a pull request through the host's raw API"
HARD_RESET = "a hard reset"
BRANCH_DELETE = "force-deleting a branch"

# What each class's refusal says, so a row is refused for its own reason and
# not for another rule's.
REASONS = {
    AMEND: "amending",
    PUSH: "bypass review",
    FORCE_PUSH: "bypass review",
    MERGE: "never merges",
    RAW_MERGE: "never merges",
    HARD_RESET: "reset --hard",
    BRANCH_DELETE: "force-deleting",
}


def judge_rows(*labels: str, wrappers: bool | None = None) -> list[tuple[str, Spelling]]:
    """The table's judge rows of the classes named, or of all: only the wrapper
    rows when `wrappers` is true, none of them when false."""
    rows = [
        (label, spelling)
        for label, spellings in SPELLINGS.items()
        if not labels or label in labels
        for spelling in spellings
        if Reader.JUDGE in spelling.readers
        and (wrappers is None or (spelling.name in WRAPPERS) == wrappers)
    ]
    assert rows, f"the table has no judge rows for {labels or 'any class'}"
    return rows


def refused_wrongly(rows: Iterable[tuple[str, Spelling]]) -> dict[str, str]:
    """The rows the rules do not refuse for their class's own reason, by
    command, with what they said instead."""
    wrong: dict[str, str] = {}
    for label, spelling in rows:
        verdict = check_command(spelling.command, branch=probe_branch())
        if verdict.allowed or REASONS[label] not in verdict.reason:
            wrong[spelling.command] = verdict.reason or "allowed"
    return wrong


def judged_differently(
    rows: Iterable[tuple[str, Spelling]],
    reword: Callable[[str], str | None],
    *,
    allowed: bool,
    reason: str = "",
) -> dict[str, str]:
    """For each row, the command `reword` makes of it (None skips the row),
    when the rules judge it other than `allowed` — or, when refused, without
    `reason` in what they say."""
    wrong: dict[str, str] = {}
    for _label, spelling in rows:
        command = reword(spelling.command)
        if command is None:
            continue
        verdict = check_command(command, branch=probe_branch())
        if verdict.allowed != allowed or (not allowed and reason not in verdict.reason):
            wrong[command] = verdict.reason or "allowed"
    return wrong
