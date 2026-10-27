"""Recording a hand merge of held work (spec: external-work)."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore


class HandMergeRefused(ValueError):
    """A hand merge that cannot be recorded; the message says why."""


def record_hand_merge(
    inst: Installation,
    store: UnitStore,
    change: str,
    groups: Sequence[int],
    *,
    pr: int | None = None,
    commit: str | None = None,
) -> None:
    """Verify the pull request `pr` is merged, or `commit` is on the repo's default branch, then
    record `groups` of `change` as built by hand. Raises `HandMergeRefused` otherwise."""
    raise NotImplementedError
