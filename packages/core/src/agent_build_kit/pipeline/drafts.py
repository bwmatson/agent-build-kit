"""A unit's state, written onto its pull request as a draft or not.

Cosmetic by construction: nothing here raises. The state is written when a unit
changes state (`follow`), and `reconcile` writes it again onto a pull request
the last poll read otherwise; the caller decides when that runs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agent_build_kit.pipeline.label_sweep import capped_by_repo
from agent_build_kit.pipeline.labels import ForRepo
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING


def wanted_draft(unit: StoredUnit) -> tuple[int, bool] | None:
    """The unit's pull request and the draft state it calls for: a draft while the unit runs or
    waits, ready in review. None for a unit with no pull request or in another state."""
    if unit.pr is None or unit.state not in (RUNNING, PLANNED, IN_REVIEW):
        return None
    return unit.pr, unit.state != IN_REVIEW


class StateDrafts:
    def __init__(self, for_repo: ForRepo, *, log: Callable[[str], None] = print) -> None:
        self.for_repo = for_repo
        self.log = log
        self._said_no_drafts = False
        # The repos whose host keeps no drafts, and the failures already logged.
        self._no_drafts: set[str] = set()
        self._failed: set[tuple[str, int, bool]] = set()

    def follow(self, unit: StoredUnit, units: list[StoredUnit], *, opened: bool) -> None:
        """Make the unit's pull request a draft while it runs or waits, ready in review."""
        if opened or (wanted := wanted_draft(unit)) is None:
            return
        self._write(unit.repo, *wanted)

    def reconcile(
        self,
        units: list[StoredUnit],
        recorded: Callable[[str, int], bool | None],
        *,
        limit: int,
        repo_order: Sequence[str],
    ) -> None:
        """Write the draft state each unit calls for onto a pull request the poll recorded
        otherwise, at most `limit` writes, lowest number first within each repo, repos in
        `repo_order`. A repo whose host keeps no drafts is skipped and the others go on."""
        mismatched: dict[tuple[str, int], bool] = {}
        for unit in units:
            if (wanted := wanted_draft(unit)) is None:
                continue
            pr, draft = wanted
            seen = recorded(unit.repo, pr)
            if seen is not None and seen != draft:
                mismatched[(unit.repo, pr)] = draft
        chosen, remaining = capped_by_repo(
            [pair for pair in mismatched if pair[0] not in self._no_drafts], repo_order, limit
        )
        for repo, pr in chosen:
            if repo not in self._no_drafts:
                self._write(repo, pr, mismatched[(repo, pr)])
        if remaining:
            self.log(f"draft: {remaining} more to reconcile at the next poll")

    def _write(self, repo: str, pr: int, draft: bool) -> None:
        """Set the draft state; never raises. A failure is logged once per repo, pull request
        and state wanted, and forgotten on a success."""
        key = (repo, pr, draft)
        try:
            forge, repo_id = self.for_repo(repo)
            forge.set_draft(repo_id, pr, draft)
        except NotImplementedError:
            # A host with no drafts is not a fault, and saying so on every
            # state change would read as one.
            self._no_drafts.add(repo)
            if not self._said_no_drafts:
                self._said_no_drafts = True
                self.log("draft: this host keeps no drafts, so none are set")
        except Exception as error:
            if key not in self._failed:
                self._failed.add(key)
                what = f"setting #{pr} to draft={draft}"
                self.log(f"draft: {what} failed - {type(error).__name__}: {error}")
        else:
            self._failed.discard(key)
