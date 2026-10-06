"""A unit's state, written onto its pull request as a draft or not.

Cosmetic by construction: nothing here raises, and nothing reads the draft
state back.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING

ForRepo = Callable[[str], tuple[Forge, RepoId]]


class StateDrafts:
    def __init__(self, for_repo: ForRepo, *, log: Callable[[str], None] = print) -> None:
        self.for_repo = for_repo
        self.log = log
        self._said_no_drafts = False

    def follow(self, unit: StoredUnit, units: list[StoredUnit], *, opened: bool) -> None:
        """Make the unit's pull request a draft while it runs, ready in review."""
        if opened or unit.pr is None or unit.state not in (RUNNING, IN_REVIEW):
            return
        draft = unit.state == RUNNING
        try:
            forge, repo_id = self.for_repo(unit.repo)
            forge.set_draft(repo_id, unit.pr, draft)
        except NotImplementedError:
            # A host with no drafts is not a fault, and saying so on every
            # state change would read as one.
            if not self._said_no_drafts:
                self._said_no_drafts = True
                self.log("draft: this host keeps no drafts, so none are set")
        except Exception as error:
            what = f"setting #{unit.pr} to draft={draft}"
            self.log(f"draft: {what} failed - {type(error).__name__}: {error}")
