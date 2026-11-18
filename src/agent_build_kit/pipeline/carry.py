"""Carry a unit that landed off the default branch onto it."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.pipeline.restack import Resolver
from agent_build_kit.pipeline.unit_store import UnitStore


def carry(
    store: UnitStore,
    unit_id: str,
    *,
    forge: Forge,
    repo_id: RepoId,
    repo: Path,
    default_branch: str,
    worktrees: Path,
    resolve: Resolver | None = None,
) -> None:
    """Cherry-pick the unit's merge commit onto `spec/<unit>/carry`, a branch off the default
    branch made in a worktree under `worktrees`, and open a pull request against the default
    branch, recorded as role `carry`. The unit is `in_review` with cause `carried`; one that
    already carries is left alone, and a cherry-pick that leaves nothing to commit opens no pull
    request and records the unit `merged`."""
    raise NotImplementedError
