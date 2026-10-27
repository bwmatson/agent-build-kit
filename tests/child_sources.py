"""Guard support: a test module that builds a child pytest's source as a string."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from tests.tracked_files import ROOT

RUNNERS: frozenset[str] = frozenset()
ALLOWED: Mapping[str, str] = {}


def source_hits(text: str) -> list[int]:
    """Lines of string constants that define a test, fixture or hook, in a module that also calls
    a name of `RUNNERS`."""
    raise NotImplementedError


def check_tests(
    files: Iterable[Path], allowed: Mapping[str, str] = ALLOWED, root: Path = ROOT
) -> list[str]:
    """`path:line` of each hit in a module not allowed, and a stale-entry line for each allowed
    module with no hit; files under `tests/child_modules/` are exempt."""
    raise NotImplementedError
