"""Whether a clean move onto a moved base is checked by what it can affect, or in full."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit.config import RestackCheck
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git
from agent_build_kit.profiles.base import is_doc_path


class MoveScope(Frozen):
    """How a moved base is checked: `scoped` over the files the move brought in, or in full
    for `reason`."""

    scoped: bool
    reason: str = ""
    incoming: list[str] = []


class FileKinds(Frozen):
    """How many files of a set are changelog, document, test and code files."""

    changelog: int = 0
    documents: int = 0
    tests: int = 0
    code: int = 0


def kinds_of(
    paths: Sequence[str], is_test: Callable[[str], bool], changelog: str | None
) -> FileKinds:
    """`paths` counted by kind, in the order changelog (the repo's `changelog` path; none when
    it keeps no changelog), document, test, code."""
    counts = {"changelog": 0, "documents": 0, "tests": 0, "code": 0}
    for path in paths:
        if changelog is not None and path == changelog:
            counts["changelog"] += 1
        elif is_doc_path(path):
            counts["documents"] += 1
        elif is_test(path):
            counts["tests"] += 1
        else:
            counts["code"] += 1
    return FileKinds(**counts)


class FilesNotListed(Exception):
    """The files a move brought in could not be listed; the message says why."""


def incoming_files(tree: Path, moved_from: str, base: str) -> list[str]:
    """The files that differ between `moved_from`, the base a restack computed, and `base`:
    what the move brought in. Raises `FilesNotListed` when git cannot say."""
    listed = git(tree, "diff", "--name-only", moved_from, base, check=False)
    if listed.returncode != 0:
        why = next((line for line in listed.stderr.splitlines() if line.strip()), "git failed")
        raise FilesNotListed(why)
    return [line for line in listed.stdout.splitlines() if line.strip()]


def brought_in(tree: Path, moved_from: str, base: str) -> tuple[str, ...]:
    """`incoming_files` for a record of the move: none when the files cannot be listed, since a
    record never replaces the result of what it describes."""
    if not moved_from:
        return ()
    try:
        return tuple(incoming_files(tree, moved_from, base))
    except (FilesNotListed, OSError):
        return ()


def scope_of(own: Sequence[str], incoming: Sequence[str], setting: RestackCheck) -> MoveScope:
    """The rule over the files the unit changes and the files the move brought in.

    Scoped unless the setting says full, the unit changed nothing of its own, or a file the
    move brought in is one the unit changes, which git merging cleanly says nothing about."""
    if setting is RestackCheck.FULL:
        return MoveScope(scoped=False, reason="global_limits.restack_check is full")
    if not own:
        return MoveScope(scoped=False, reason="the unit produced nothing of its own")
    shared = sorted(set(own) & set(incoming))
    if shared:
        return MoveScope(
            scoped=False,
            reason=f"a file the unit changes was brought in: {', '.join(shared)}",
        )
    return MoveScope(scoped=True, incoming=list(incoming))


def moved_base_scope(
    tree: Path, *, own: Sequence[str], base: str, moved_from: str, setting: RestackCheck
) -> MoveScope:
    """`scope_of` over `own`, the files the unit changes, and the files that differ between
    `moved_from`, the base the restack computed, and `base`.

    A base that cannot be diffed is not an empty move: it is full, with the failure as the
    reason."""
    if setting is RestackCheck.FULL:
        return scope_of(own, [], setting)
    if not moved_from:
        return MoveScope(scoped=False, reason="the move has no old base")
    try:
        incoming = incoming_files(tree, moved_from, base)
    except FilesNotListed as error:
        return MoveScope(
            scoped=False, reason=f"the files the move brought in could not be listed: {error}"
        )
    return scope_of(own, incoming, setting)
