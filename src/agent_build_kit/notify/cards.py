"""The cards the units call for."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from agent_build_kit import config, forges
from agent_build_kit.model import Frozen
from agent_build_kit.notify.provider import CardKind
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.audit_record import AWAITING, UnreadableAudits, read_audits
from agent_build_kit.pipeline.demotion_record import (
    UnreadableDemotions,
    read_demotions,
    standing_demotions,
)
from agent_build_kit.pipeline.demotion_record import (
    demoted_classes as standing_classes,
)
from agent_build_kit.pipeline.landing import declined_reason
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, StoredUnit
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, MERGED
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import latest_verdict

# How far back the digest card looks for units the pipeline landed.
DIGEST_WINDOW = timedelta(hours=24)

# Held for a reason a person has to act on: the review loop or the toolchain stopped it, or
# it said it needs one. Depth clears itself, and the reviewer's hold is the person's own.
_NEEDS_A_PERSON = (HeldBy.REVIEW, HeldBy.TOOLCHAIN)

_WORDING = {
    CardKind.REVIEW: "Ready for review",
    CardKind.FAILED: "Failed",
    CardKind.HELD: "Held, waiting for a person",
    CardKind.DIGEST: "Landed without a person",
    CardKind.AUDIT: "Landed without a person, awaiting audit",
    CardKind.DEMOTION: "Demoted, held at light and not landed",
}


class Card(Frozen):
    id: str
    kind: CardKind
    title: str
    body: str
    link: str
    # False for a card that is shown once and never sounded again.
    remind: bool = True


def _kind_of(unit: StoredUnit) -> CardKind | None:
    if unit.state == IN_REVIEW and not unit.feedback:
        return CardKind.REVIEW
    if unit.state == FAILED:
        return CardKind.FAILED
    if unit.state == HELD and (unit.held_by in _NEEDS_A_PERSON or unit.cause is Cause.NEEDS_HUMAN):
        return CardKind.HELD
    return None


def _landed_at(unit: StoredUnit) -> datetime | None:
    """When the pipeline landed the unit, from its history; none for a unit it did not land."""
    if unit.state != MERGED:
        return None
    for entry in reversed(unit.history):
        if entry.get("cause") == Cause.AUTO_LANDED.value:
            return datetime.fromisoformat(entry["at"])
    return None


def _will_land(unit: StoredUnit, unit_class: str | None, demoted_classes: Collection[str]) -> bool:
    """Whether the landing step will land a unit whose verdict is `auto`: its class is listed
    and not demoted, its forge merges, and it was not declined for a reason other than checks
    still pending."""
    review = config.active().review
    forge, _ = forges.for_repo(unit.repo)
    return (
        review.enabled
        and unit_class is not None
        and unit_class in review.auto_land.classes
        and unit_class not in demoted_classes
        and forge.merges
        and not declined_reason(unit)
    )


def _digest(units: Sequence[StoredUnit], verdicts: Path | None) -> Card | None:
    """One card listing the units landed in the last 24 hours, none when there are none."""
    since = spans.clock.now() - DIGEST_WINDOW
    landed = sorted(
        (at, unit) for unit in units if (at := _landed_at(unit)) is not None and at >= since
    )
    if not landed:
        return None
    lines = []
    for _, unit in landed:
        recorded = latest_verdict(verdicts, unit.id) if verdicts is not None else None
        forge, repo = forges.for_repo(unit.repo)
        unit_class = recorded.unit_class if recorded else "unclassified"
        lines.append(f"{unit.id} ({unit_class}) {unit.title} {forge.web_url(repo, pr=unit.pr)}")
    count = len(landed)
    return Card(
        id=f"digest:{landed[-1][0].date()}",
        kind=CardKind.DIGEST,
        title=f"{count} unit{'s' if count != 1 else ''} landed without a person",
        body="\n".join(lines),
        link=lines[-1].rsplit(" ", 1)[1],
        remind=False,
    )


def _audit_cards(units: Sequence[StoredUnit], audits: Path) -> list[Card]:
    """One card for each landed unit awaiting audit."""
    try:
        recorded = read_audits(audits)
    except UnreadableAudits:
        return []
    waiting = {id: r for id, r in recorded.items() if r.get("state") == AWAITING}
    cards = []
    for unit in units:
        if unit.id not in waiting:
            continue
        forge, repo = forges.for_repo(unit.repo)
        cards.append(
            Card(
                id=f"audit:{unit.id}",
                kind=CardKind.AUDIT,
                title=f"{unit.id} {unit.title}",
                body=f"{_WORDING[CardKind.AUDIT]} ({waiting[unit.id]['unit_class']}): "
                f"`abk review audit {unit.id} ok|wrong`",
                link=forge.web_url(repo, pr=unit.pr),
            )
        )
    return cards


def _demotion_cards(demotions: Path) -> list[Card]:
    """One card for each class whose demotion stands, and for 24 hours a notice of each lift."""
    try:
        standing = standing_demotions(demotions)
        recorded = read_demotions(demotions)
    except UnreadableDemotions:
        return []
    cards = [
        Card(
            id=f"demotion:{d.name}:{d.since}",
            kind=CardKind.DEMOTION,
            title=f"{d.name} demoted",
            body=f"{_WORDING[CardKind.DEMOTION]}: {d.name} by {d.trigger} on "
            f"{d.unit}; `abk review reinstate {d.name}` lifts it",
            link="",
        )
        for d in standing
    ]
    now = spans.clock.now()
    for name, record in sorted(recorded.items()):
        lifted = record["lifted"]
        if lifted is not None and now - datetime.fromisoformat(lifted) < DIGEST_WINDOW:
            cards.append(
                Card(
                    id=f"demotion-lifted:{name}:{lifted}",
                    kind=CardKind.DEMOTION,
                    title=f"{name} reinstated",
                    body=f"Demotion of {name} lifted",
                    link="",
                    remind=False,
                )
            )
    return cards


def desired_cards(
    units: Sequence[StoredUnit],
    verdicts: Path | None = None,
    *,
    demoted_classes: Collection[str] = (),
    audits: Path | None = None,
    demotions: Path | None = None,
) -> list[Card]:
    """One card for each unit that is waiting on a person, and one digest of what landed.

    `verdicts` is the verdict file; `demoted_classes` are classes held back from landing besides
    those in `demotions`, the demotion file (an unreadable one holds every class back);
    `audits` is the audit file."""
    held_back = set(demoted_classes)
    unreadable = False
    if demotions is not None:
        try:
            held_back.update(standing_classes(demotions))
        except UnreadableDemotions:
            unreadable = True
    cards = []
    for unit in units:
        kind = _kind_of(unit)
        if kind is None:
            continue
        if kind is CardKind.REVIEW and verdicts is not None:
            recorded = latest_verdict(verdicts, unit.id)
            if (
                recorded is not None
                and recorded.tier is ReviewTier.AUTO
                and not unreadable
                and _will_land(unit, recorded.unit_class, held_back)
            ):
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
    if audits is not None:
        cards.extend(_audit_cards(units, audits))
    if demotions is not None:
        cards.extend(_demotion_cards(demotions))
    digest = _digest(units, verdicts)
    return [*cards, digest] if digest else cards
