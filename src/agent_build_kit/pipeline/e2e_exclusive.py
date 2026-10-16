"""A test is in at most one e2e-test split: found by listing each split through the profile."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Collection

from agent_build_kit.config import E2eSplit
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.e2e import build_selection
from agent_build_kit.profiles.base import AppliesE2eSelection, ListsRegisteredSelectors


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
    toolchain: AppliesE2eSelection,
    command: list[str],
    marker: str,
    splits: Collection[E2eSplit],
    *,
    run: Callable[..., subprocess.CompletedProcess],
) -> SplitCheck:
    """List each split's tests and `rest` through `toolchain` for `command`, and name every
    test selected by two splits, every selector the runner does not register and every
    listing that failed."""
    declared = [split for split in splits if split.marker is not None]
    if not declared:
        return SplitCheck()
    findings: list[str] = []
    listings: list[SplitListing] = []
    for split in splits:
        selection = build_selection(marker, splits, only=split.name)
        tests = toolchain.list_tests(command, selection, run=run)
        if tests is None:
            findings.append(f"the listing of split {split.name} failed; it says nothing about it")
        listings.append(
            SplitListing(
                name=split.name,
                marker=split.marker,
                tests=None if tests is None else tuple(tests),
            )
        )
    owners: dict[str, list[str]] = {}
    for listing in listings:
        if listing.marker is None:
            continue
        for test in listing.tests or ():
            owners.setdefault(test, []).append(listing.name)
    for test, names in owners.items():
        if len(names) > 1:
            findings.append(f"{test} is in splits {' and '.join(names)}")
    if isinstance(toolchain, ListsRegisteredSelectors):
        known = toolchain.registered_selectors(command, run=run)
        if known is None:
            findings.append("the listing of the runner's registered selectors failed")
        else:
            findings.extend(
                f"unknown selector {split.marker} of split {split.name}: "
                "the runner does not register it"
                for split in declared
                if split.marker not in known
            )
    return SplitCheck(listings=tuple(listings), findings=tuple(findings))
