"""The cards the units call for."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit import forges
from agent_build_kit.model import Frozen
from agent_build_kit.notify.provider import CardKind
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, StoredUnit
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW

# Held for a reason a person has to act on: the review loop or the toolchain stopped it, or
# it said it needs one. Depth clears itself, and the reviewer's hold is the person's own.
_NEEDS_A_PERSON = (HeldBy.REVIEW, HeldBy.TOOLCHAIN)

_WORDING = {
    CardKind.REVIEW: "Ready for review",
    CardKind.FAILED: "Failed",
    CardKind.HELD: "Held, waiting for a person",
}


class Card(Frozen):
    id: str
    kind: CardKind
    title: str
    body: str
    link: str


def _kind_of(unit: StoredUnit) -> CardKind | None:
    if unit.state == IN_REVIEW and not unit.feedback:
        return CardKind.REVIEW
    if unit.state == FAILED:
        return CardKind.FAILED
    if unit.state == HELD and (unit.held_by in _NEEDS_A_PERSON or unit.cause is Cause.NEEDS_HUMAN):
        return CardKind.HELD
    return None


def desired_cards(units: Sequence[StoredUnit], verdicts: Path | None = None) -> list[Card]:
    """One card for each unit that is waiting on a person.

    `verdicts` is the verdict file; a unit in review whose recorded tier is `auto` raises none."""
    if verdicts is not None:
        raise NotImplementedError
    cards = []
    for unit in units:
        kind = _kind_of(unit)
        if kind is None:
            continue
        forge, repo = forges.for_repo(unit.repo)
        wording = _WORDING[kind]
        cards.append(
            Card(
                id=f"unit:{kind}:{unit.id}",
                kind=kind,
                title=f"{unit.id} {unit.title}",
                body=f"{wording}: {unit.note}" if unit.note else wording,
                link=forge.web_url(repo, pr=unit.pr),
            )
        )
    return cards
