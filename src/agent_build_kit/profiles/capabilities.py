"""The capability protocols the framework branches on, and the check that every profile has them.

A profile that cannot support a capability is listed in `GAP_BASELINE`, which may only shrink.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

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

# `(profile name, protocol name)` of each capability a profile does not provide yet.
GAP_BASELINE: frozenset[tuple[str, str]] = frozenset()


def capability_problems(
    profiles: Mapping[str, ToolchainProfile],
    *,
    capabilities: Sequence[type] = CAPABILITIES,
    baseline: frozenset[tuple[str, str]] = GAP_BASELINE,
) -> list[str]:
    """What is wrong with `profiles`: a capability one lacks that the baseline does not list
    (naming both), a baseline entry the profile has since filled, and an entry `GAP_BASELINE`
    does not hold."""
    raise NotImplementedError


def selector_problems(profile: ToolchainProfile, repo: Path, files: Sequence[str]) -> list[str]:
    """What is wrong with the profile's six selector capabilities over the project at `repo`:
    one missing, or a file among `files` declaring more than one kind."""
    raise NotImplementedError
