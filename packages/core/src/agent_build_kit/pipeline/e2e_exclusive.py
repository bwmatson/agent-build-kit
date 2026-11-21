"""A test is in at most one e2e-test split: found by listing each split through the profile."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Collection, Mapping

from agent_build_kit.config import E2eDimensionValue, E2eSplit
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.e2e import E2eSelection, build_selection
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


def values_carried_twice(
    markers: Collection[str], dimensions: Mapping[str, Mapping[str, E2eDimensionValue]]
) -> dict[str, tuple[str, ...]]:
    """For each dimension of which a test with `markers` carries two or more values, those values.
    The one rule that a test carries at most one value of a dimension."""
    carried = {
        dimension: tuple(value for value, entry in values.items() if entry.marker in markers)
        for dimension, values in dimensions.items()
    }
    return {dimension: found for dimension, found in carried.items() if len(found) > 1}


def check_dimensions(
    toolchain: AppliesE2eSelection,
    command: list[str],
    marker: str,
    dimensions: Mapping[str, Mapping[str, E2eDimensionValue]],
    splits: Collection[E2eSplit],
    *,
    run: Callable[..., subprocess.CompletedProcess],
) -> SplitCheck:
    """List each dimension value's tests through `toolchain` for `command`, and name every test
    carrying two values of one dimension, every marker shared by two values or a split and every
    marker the runner does not register."""
    findings: list[str] = []
    listings: list[SplitListing] = []
    owners: dict[str, list[str]] = {}
    for split in splits:
        if split.marker is not None:
            owners.setdefault(split.marker, []).append(f"split {split.name}")
    for dimension, values in dimensions.items():
        for value, entry in values.items():
            owners.setdefault(entry.marker, []).append(f"{dimension}={value}")
    for tag, names in owners.items():
        if len(names) > 1:
            findings.append(f"marker {tag} is used by {' and '.join(names)}")
    markers_of: dict[str, set[str]] = {}
    for dimension, values in dimensions.items():
        for value, entry in values.items():
            selection = E2eSelection(marker=marker, any_of=(entry.marker,))
            tests = toolchain.list_tests(command, selection, run=run)
            if tests is None:
                findings.append(
                    f"the listing of {dimension}={value} failed; it says nothing about it"
                )
            listings.append(
                SplitListing(
                    name=f"{dimension}={value}",
                    marker=entry.marker,
                    tests=None if tests is None else tuple(tests),
                )
            )
            for test in tests or ():
                markers_of.setdefault(test, set()).add(entry.marker)
    for test, markers in markers_of.items():
        for dimension, found in values_carried_twice(markers, dimensions).items():
            findings.append(
                f"{test} carries {len(found)} values of {dimension}: {' and '.join(found)}"
            )
    if isinstance(toolchain, ListsRegisteredSelectors):
        known = toolchain.registered_selectors(command, run=run)
        if known is None:
            findings.append("the listing of the runner's registered selectors failed")
        else:
            findings.extend(
                f"unknown selector {entry.marker} of {dimension}={value}: "
                "the runner does not register it"
                for dimension, values in dimensions.items()
                for value, entry in values.items()
                if entry.marker not in known
            )
    return SplitCheck(listings=tuple(listings), findings=tuple(findings))
