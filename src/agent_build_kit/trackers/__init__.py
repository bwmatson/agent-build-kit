"""The work-tracker seam: a `Tracker` protocol beside the `Forge` one."""

from __future__ import annotations

from collections.abc import Callable

from agent_build_kit.trackers.base import Tracker
from agent_build_kit.trackers.config import TrackerConfigError, TrackerSection, section_for

__all__ = ["TrackerConfigError", "enabled", "for_repo", "register", "unregister"]

Factory = Callable[[TrackerSection], Tracker]

_REGISTRY: dict[str, Factory] = {}


def register(kind: str, factory: Factory) -> None:
    """Make the tracker of a section of this `kind` available: each tracker change
    registers its own, and the seam ships none."""
    _REGISTRY[kind] = factory


def unregister(kind: str) -> None:
    """Forget the factory registered for `kind`; a kind with none is left alone."""
    _REGISTRY.pop(kind, None)


def for_repo(name: str) -> Tracker | None:
    """The tracker of a repo in the active workspace; None when the capability is off.

    Raises TrackerConfigError for an invalid section, and for a valid one whose kind has no
    factory registered.
    """
    section = section_for(name)
    if section is None:
        return None
    factory = _REGISTRY.get(section.kind)
    if factory is None:
        raise TrackerConfigError(f"repo {name!r}: no tracker is implemented for {section.kind!r}")
    return factory(section)


def enabled(name: str) -> bool:
    """Whether the repo's configuration names a tracker.

    Raises TrackerConfigError for a present but invalid section, as `for_repo` does.
    """
    return section_for(name) is not None
