"""The work-tracker seam: a `Tracker` protocol beside the `Forge` one."""

from __future__ import annotations

from agent_build_kit.trackers.base import Tracker
from agent_build_kit.trackers.config import TrackerConfigError, section_for

__all__ = ["TrackerConfigError", "enabled", "for_repo"]


def for_repo(name: str) -> Tracker | None:
    """The tracker of a repo in the active workspace; None when the capability is off.

    Raises TrackerConfigError for an invalid section, and for a valid one whose kind has
    no implementation yet: the seam ships none, each tracker change registers its own.
    """
    section = section_for(name)
    if section is None:
        return None
    raise TrackerConfigError(f"repo {name!r}: no tracker is implemented for {section.kind!r}")


def enabled(name: str) -> bool:
    """Whether the repo's configuration names a tracker."""
    return section_for(name) is not None
