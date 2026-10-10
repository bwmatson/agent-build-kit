"""Path patterns relative to a repository root: the one matcher behind the environment's
input hash, its comparison against the base, and the ownership of lock files and artifacts.

A pattern uses `/` separators. `*` matches within one path component, `?` one character,
`[...]` a class, and `**` as a whole component any number of directories, none included. A
pattern naming a directory matches every file under it. `.git` is never matched.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterable, Sequence
from functools import cache
from pathlib import Path, PurePosixPath

GIT_DIR = ".git"
_WILDCARDS = re.compile(r"[*?\[]")


def normalize(pattern: str) -> str:
    """The pattern as a clean relative path; ValueError when it is empty, absolute or
    leaves the repository."""
    if not pattern.strip():
        raise ValueError("the pattern must not be empty")
    if pattern.startswith("/") or PurePosixPath(pattern).is_absolute():
        raise ValueError(f"{pattern!r} is absolute; patterns are relative to the repository")
    if ".." in pattern.split("/"):
        raise ValueError(f"{pattern!r} contains `..`; patterns stay inside the repository")
    return PurePosixPath(os.path.normpath(pattern)).as_posix()


def is_outside_literal(pattern: str) -> bool:
    """Whether `pattern` is a wildcard-free relative path that leaves the repository, such
    as a sibling checkout's manifest. Inputs may still list one for a release; it is
    hashed, but owns no file in a worktree."""
    if not pattern.strip() or pattern.startswith("/") or _WILDCARDS.search(pattern):
        return False
    parts = PurePosixPath(os.path.normpath(pattern)).parts
    return not PurePosixPath(pattern).is_absolute() and parts[:1] == ("..",)


def inside(patterns: Iterable[str]) -> list[str]:
    """The patterns that stay inside the repository."""
    return [pattern for pattern in patterns if not is_outside_literal(pattern)]


def validate(patterns: list[str], *, allow_outside: bool = False) -> list[str]:
    """`patterns` unchanged, or ValueError naming the first that is not a valid pattern.
    `allow_outside` lets a wildcard-free path leaving the repository through."""
    for pattern in patterns:
        if not (allow_outside and is_outside_literal(pattern)):
            normalize(pattern)
    return patterns


@cache
def _component(piece: str) -> re.Pattern[str]:
    return re.compile(fnmatch.translate(piece))


def _match(pieces: tuple[str, ...], parts: tuple[str, ...]) -> bool:
    if not pieces:
        return True  # the pattern named this directory, so everything under it matches
    head, rest = pieces[0], pieces[1:]
    if head == "**":
        return any(_match(rest, parts[skipped:]) for skipped in range(len(parts) + 1))
    if not parts:
        return False
    return bool(_component(head).fullmatch(parts[0])) and _match(rest, parts[1:])


def matches(pattern: str, path: str) -> bool:
    """Whether `path` (relative, `/`-separated) is matched by `pattern`."""
    if is_outside_literal(pattern):
        return False  # a worktree-relative path never leaves the repository
    parts = tuple(part for part in path.split("/") if part and part != ".")
    if GIT_DIR in parts:
        return False
    if not parts:
        return False
    return _match(tuple(normalize(pattern).split("/")), parts)


def matches_any(patterns: Iterable[str], path: str) -> bool:
    return any(matches(pattern, path) for pattern in patterns)


def _start(pattern: str) -> str:
    """The longest leading run of components with no wildcard: where a walk can begin."""
    leading: list[str] = []
    for piece in normalize(pattern).split("/"):
        if _WILDCARDS.search(piece):
            break
        leading.append(piece)
    return "/".join(leading)


def matching_files(
    root: Path, patterns: Sequence[str], *, excluding: Sequence[str] = ()
) -> dict[str, list[str]]:
    """Per pattern, the sorted files under `root` it matches, leaving out `.git` and
    anything under a path `excluding` matches. A folder `excluding` matches is not entered."""
    found: dict[str, list[str]] = {}
    for pattern in patterns:
        if is_outside_literal(pattern):
            literal = os.path.normpath(pattern)
            found[pattern] = [literal] if (root / literal).is_file() else []
            continue
        start = _start(pattern)
        hits: set[str] = set()
        origin = root / start if start else root
        if origin.is_file():
            candidates = [start]
        else:
            candidates = []
            for folder, folders, files in os.walk(origin):
                here = Path(folder).relative_to(root).as_posix()
                folders[:] = [
                    name
                    for name in folders
                    if name != GIT_DIR
                    and not matches_any(excluding, f"{'' if here == '.' else here + '/'}{name}")
                ]
                candidates.extend(f"{'' if here == '.' else here + '/'}{name}" for name in files)
        for name in candidates:
            if matches(pattern, name) and not matches_any(excluding, name):
                hits.add(name)
        found[pattern] = sorted(hits)
    return found
