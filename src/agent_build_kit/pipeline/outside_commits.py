"""Commits made to a unit's branch by a session that is not its build session.

A chat commit carries its session in an `Adopted-From` trailer. Comparing that with the build
session the unit's thread recorded finds the commits the build agent did not make, so nothing
is stored for them. The unit's next rework, check-fix and review prompts list them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git, git_out

_FIELD, _RECORD = "\x1f", "\x1e"

OUTSIDE_COMMITS_NOTE = """\
**Commits made outside this session.** A person changed this branch through another \
session. These commits are authoritative: do not revert them, and read their files again \
before relying on what you remember of them.

{commits}
"""

OUTSIDE_TESTS_NOTE = """\
Tests changed by these commits: {tests}. If you change one of them, state whether you \
keep, adapt or retire it, and why.
"""


class OutsideCommit(Frozen):
    commit: str
    subject: str
    session: str
    files: tuple[str, ...]


def outside_commits(tree: Path, ref: str, build_session: str) -> list[OutsideCommit]:
    """The commits on `ref..HEAD` whose `Adopted-From` session is not `build_session`, oldest
    first. A branch the range cannot be read for has none."""
    if not tree.is_dir():
        return []
    done = git(
        tree,
        "log",
        "--reverse",
        f"--format=%H{_FIELD}%s{_FIELD}%(trailers:key=Adopted-From,valueonly,separator=){_RECORD}",
        f"{ref}..HEAD",
        check=False,
    )
    if done.returncode:
        return []
    found = []
    for record in done.stdout.split(_RECORD):
        if not record.strip():
            continue
        commit, subject, session = (part.strip() for part in record.split(_FIELD))
        if not session or session == build_session:
            continue
        files = git_out(tree, "diff-tree", "--no-commit-id", "--name-only", "-r", commit)
        found.append(
            OutsideCommit(
                commit=commit,
                subject=subject,
                session=session,
                files=tuple(files.splitlines()),
            )
        )
    return found


def outside_commits_note(
    tree: Path, ref: str, build_session: str, *, is_test: Callable[[str], bool]
) -> str:
    """The prompt part listing the outside commits, or nothing when there are none."""
    commits = outside_commits(tree, ref, build_session)
    if not commits:
        return ""
    listed = "\n".join(
        f"- {c.commit[:9]} {c.subject} (session {c.session}; files: {', '.join(c.files)})"
        for c in commits
    )
    note = OUTSIDE_COMMITS_NOTE.format(commits=listed)
    tests = sorted({f for c in commits for f in c.files if is_test(f)})
    if tests:
        note += "\n" + OUTSIDE_TESTS_NOTE.format(tests=", ".join(tests))
    return note
