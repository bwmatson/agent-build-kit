"""A test is in at most one tier 2 split: found by listing each split through the profile."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Collection

from agent_build_kit.config import Tier2Split
from agent_build_kit.model import Frozen


class SplitListing(Frozen):
    """What listing one split (or `rest`) gave: its tests, None when the listing failed."""

    name: str
    marker: str | None = None
    tests: tuple[str, ...] | None = None


class SplitCheck(Frozen):
    """The listing of every split and the findings: a test in two splits, a selector the
    runner does not register, a listing that failed."""

    listings: tuple[SplitListing, ...] = ()
    findings: tuple[str, ...] = ()


def check_splits(
    toolchain: object,
    command: list[str],
    marker: str,
    splits: Collection[Tier2Split],
    *,
    run: Callable[..., subprocess.CompletedProcess],
) -> SplitCheck:
    """List each split's tests and `rest` through `toolchain` for `command`, and name every
    test selected by two splits, every selector the runner does not register and every
    listing that failed."""
    raise NotImplementedError
