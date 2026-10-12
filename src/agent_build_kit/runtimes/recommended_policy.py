"""The recommended policy for a build agent, as one table.

Per forbidden class: the command globs that refuse it, the samples they must and
must not match, and what the recommendation does not cover.
"""

from __future__ import annotations

from collections.abc import Iterable

from agent_build_kit.model import Frozen


class ClassPolicy(Frozen):
    label: str
    globs: tuple[str, ...]
    refused_samples: tuple[str, ...]
    allowed_samples: tuple[str, ...]
    # Refused samples only a glob refuses: the command rules allow them.
    glob_only: tuple[str, ...] = ()


class Uncovered(Frozen):
    label: str
    reason: str


RECOMMENDED: tuple[ClassPolicy, ...] = ()
UNCOVERED: tuple[Uncovered, ...] = ()
# Commands a glob refuses though they are harmless, and commands no glob catches.
KNOWN_FALSE_POSITIVES: tuple[str, ...] = ()
KNOWN_GAPS: tuple[str, ...] = ()
DIALECT = ""


def matches(pattern: str, command: str) -> bool:
    raise NotImplementedError


def patterns(extra: Iterable[str] = ()) -> list[str]:
    raise NotImplementedError
