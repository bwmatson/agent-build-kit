"""A unit's state, written onto its pull request as a draft or not.

Cosmetic by construction: nothing here raises, and nothing reads the draft
state back.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.pipeline.unit_store import StoredUnit

ForRepo = Callable[[str], tuple[Forge, RepoId]]


class StateDrafts:
    def __init__(self, for_repo: ForRepo, *, log: Callable[[str], None] = print) -> None:
        self.for_repo = for_repo
        self.log = log

    def follow(self, unit: StoredUnit, units: list[StoredUnit], *, opened: bool) -> None:
        """Make the unit's pull request a draft while it runs, ready in review."""
        raise NotImplementedError
