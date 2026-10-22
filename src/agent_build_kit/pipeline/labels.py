"""A unit's state, written onto its pull request.

Cosmetic by construction: nothing here raises, and no unit is decided by a label
read back; a finished unit's pull request is read only to avoid removals that
would find nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from enum import StrEnum
from pathlib import Path

from agent_build_kit.config import active
from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import latest_verdict
from agent_build_kit.pipeline.vocabulary import (
    FINISHED,
    ChecksOf,
    change_label,
    effective_state,
    review_label,
    review_label_names,
    state_label,
    state_label_names,
)

ForRepo = Callable[[str], tuple[Forge, RepoId]]


class ClearOutcome(StrEnum):
    """What taking the state labels off a pull request came to."""

    CLEARED = "cleared"
    NOTHING_TO_CLEAR = "nothing_to_clear"
    FAILED = "failed"


class StateLabels:
    def __init__(self, for_repo: ForRepo, *, log: Callable[[str], None] = print) -> None:
        self.for_repo = for_repo
        self.log = log
        self._said_no_labels = False

    def _try(self, what: str, act: Callable[[Forge, RepoId], None], repo: str) -> bool:
        try:
            forge, repo_id = self.for_repo(repo)
            act(forge, repo_id)
        except NotImplementedError:
            # A host with no label support is not a fault, and saying so on
            # every state change would read as one.
            if not self._said_no_labels:
                self._said_no_labels = True
                self.log("label: this host keeps no labels, so none are written")
            return False
        except Exception as error:
            self.log(f"label: {what} failed - {type(error).__name__}: {error}")
            return False
        return True

    def set_state(self, repo: str, pr: int, state: str) -> None:
        """Make `state` the one state label on the pull request."""
        label = state_label(state)
        if label is None:
            return
        self._try(
            f"setting {label.name} on #{pr}",
            lambda forge, repo_id: forge.set_exclusive_label(
                repo_id, pr, label, family=state_label_names()
            ),
            repo,
        )

    def set_review(self, repo: str, pr: int, tier: ReviewTier) -> None:
        """Make `tier` the one review label on the pull request."""
        label = review_label(tier)
        self._try(
            f"setting {label.name} on #{pr}",
            lambda forge, repo_id: forge.set_exclusive_label(
                repo_id, pr, label, family=review_label_names()
            ),
            repo,
        )

    def follow_review(self, unit: StoredUnit, verdicts: Path) -> None:
        """Put the review label of the unit's recorded verdict on its pull request.

        Nothing is written with review disabled, with no pull request or with no verdict.
        """
        if not active().review.enabled or unit.pr is None:
            return
        recorded = latest_verdict(verdicts, unit.id)
        if recorded is not None:
            self.set_review(unit.repo, unit.pr, recorded.tier)

    def clear_state(self, repo: str, pr: int) -> ClearOutcome:
        """Take every state label off the pull request of a finished unit.

        Reads the pull request once and removes only the state labels on it;
        which labels are state labels comes from the vocabulary, never from
        what the pull request says about the unit.
        """
        removed: list[str] = []
        unsupported = False
        names = {name.casefold() for name in state_label_names()}

        def clear(forge: Forge, repo_id: RepoId) -> None:
            nonlocal unsupported
            try:
                present = forge.labels_on(repo_id, pr)
            except NotImplementedError:
                unsupported = True
                raise
            for name in present:
                if name.casefold() in names:
                    forge.remove_label(repo_id, pr, name)
                    removed.append(name)

        if not self._try(f"clearing the state label of #{pr}", clear, repo) and not unsupported:
            return ClearOutcome.FAILED
        return ClearOutcome.CLEARED if removed else ClearOutcome.NOTHING_TO_CLEAR

    def tag_change(self, repo: str, pr: int, change: str) -> None:
        """Put the change's own label on the pull request."""
        label = change_label(change)
        self._try(
            f"adding {label.name} to #{pr}",
            lambda forge, repo_id: forge.add_label(repo_id, pr, label),
            repo,
        )

    def consume(self, repo: str, pr: int, name: str) -> bool:
        """Take an instruction label off once it has been acted on.

        Whether it came off: the caller that keeps a record of what it has
        seen must not treat a label still there as gone.
        """
        return self._try(
            f"removing {name} from #{pr}",
            lambda forge, repo_id: forge.remove_label(repo_id, pr, name),
            repo,
        )

    def follow(
        self,
        unit: StoredUnit,
        units: list[StoredUnit],
        *,
        opened: bool,
        checks_of: ChecksOf | None = None,
        paused: Collection[str] = (),
    ) -> None:
        """Bring a unit's pull request in line with its recorded state.

        What `UnitStore` calls after a state change: the state label always,
        a label for each change the unit builds (its own first) once, when the
        pull request is first recorded. A unit with no pull request has nothing to carry a label.
        """
        if unit.pr is None:
            return
        if opened:
            for member in unit.members():
                self.tag_change(unit.repo, unit.pr, member.change)
        state = effective_state(unit, units, checks_of=checks_of, paused=paused)
        if state in FINISHED:
            self.clear_state(unit.repo, unit.pr)
        else:
            self.set_state(unit.repo, unit.pr, state)
