"""Which board items a merged unit's pull request attaches to, from the levels in use."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def link_targets(
    levels: Sequence[str],
    pr_links: str | Sequence[str],
    change: str,
    built: Mapping[int, Sequence[int]],
) -> tuple[str, ...]:
    """The item keys that get the pull request of a unit that built `built` (group number to the
    numbers of its tasks) in `change`: `<change>`, `<change>:<group>` and `<change>:<group>.<task>`.
    The manual epic is never a target."""
    raise NotImplementedError
