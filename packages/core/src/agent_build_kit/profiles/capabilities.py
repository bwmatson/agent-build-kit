"""The capability protocols the framework branches on, and the check that every profile has them.

A profile that cannot support a capability is listed in `GAP_BASELINE`, which may only shrink.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from agent_build_kit.profiles.base import (
    AppliesE2eSelection,
    ListsRegisteredSelectors,
    RecordsSelectionData,
    RepeatsTests,
    ReportsRunFacts,
    RerunsFailedTests,
    SelectsAffectedTests,
    SelectsByKind,
    ToolchainProfile,
)

CAPABILITIES: tuple[type, ...] = (
    RepeatsTests,
    SelectsAffectedTests,
    RecordsSelectionData,
    ReportsRunFacts,
    AppliesE2eSelection,
    ListsRegisteredSelectors,
    RerunsFailedTests,
    SelectsByKind,
)

# The methods of `SelectsByKind`; add a method of the protocol here too.
SELECTOR_METHODS = (
    "declared_kinds",
    "default_run_leaves_out",
    "by_id_overrides_default",
    "refused_kinds",
    "kinds_of",
    "per_test_limit_option",
)

# `(profile name, protocol name)` of each capability a profile does not provide yet.
GAP_BASELINE: frozenset[tuple[str, str]] = frozenset(
    ("node-npm", capability)
    for capability in (
        "RecordsSelectionData",
        "ReportsRunFacts",
        "AppliesE2eSelection",
        "ListsRegisteredSelectors",
    )
)


def capability_problems(
    profiles: Mapping[str, ToolchainProfile],
    *,
    capabilities: Sequence[type] = CAPABILITIES,
    baseline: frozenset[tuple[str, str]] = GAP_BASELINE,
) -> list[str]:
    """What is wrong with `profiles`: a capability one lacks that the baseline does not list
    (naming both), a baseline entry the profile has since filled, and an entry `GAP_BASELINE`
    does not hold. The last guards a caller-supplied `baseline`; growth of `GAP_BASELINE`
    itself is a diff a reviewer sees."""
    problems: list[str] = []
    for name, profile in profiles.items():
        for capability in capabilities:
            listed = (name, capability.__name__) in baseline
            has = isinstance(profile, capability)
            if not has and not listed:
                problems.append(
                    f"profile {name!r} does not provide {capability.__name__}; implement it "
                    "(a new gap is not added to the baseline)"
                )
            elif has and listed:
                problems.append(
                    f"profile {name!r} now provides {capability.__name__}; remove it from the "
                    "baseline"
                )
    problems += [
        f"baseline entry ({name!r}, {capability!r}) is new; the baseline may only shrink"
        for name, capability in sorted(baseline - GAP_BASELINE)
    ]
    return problems


def selector_problems(profile: ToolchainProfile, repo: Path, files: Sequence[str]) -> list[str]:
    """What is wrong with the profile's six selector capabilities over the project at `repo`:
    one missing, or a file among `files` declaring more than one kind."""
    missing = [
        method for method in SELECTOR_METHODS if not callable(getattr(profile, method, None))
    ]
    if missing:
        return [f"profile {profile.name!r} lacks {', '.join(missing)} (SelectsByKind)"]
    selecting = cast(SelectsByKind, profile)
    problems: list[str] = []
    for path in files:
        kinds = selecting.kinds_of(repo, path)
        if len(kinds) > 1:
            problems.append(f"{path} declares more than one kind: {', '.join(kinds)}")
    return problems
