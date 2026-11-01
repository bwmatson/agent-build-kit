"""The board items a unit's pull request is linked to (spec: tracker-push)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import StoredUnit


def attach_pull_request(
    unit: StoredUnit, *, changes_dir: Path, state_dir: Path, pr_url: str
) -> tuple[str, ...]:
    """Attach the pull request to each item `pr_links` names for the groups the unit built,
    once each, recording it in the machine-local state; the keys attached this time."""
    raise NotImplementedError
