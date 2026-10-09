"""A unit's state, written onto its pull request.

Cosmetic by construction: nothing here raises, and nothing reads a label back.
"""

from __future__ import annotations

from collections.abc import Callable

from agent_build_kit.forges import Forge, RepoId
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.vocabulary import (
    ChecksOf,
    change_label,
    effective_state,
    state_label,
    state_label_names,
)

ForRepo = Callable[[str], tuple[Forge, RepoId]]


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
        self.set_state(unit.repo, unit.pr, effective_state(unit, units, checks_of=checks_of))
