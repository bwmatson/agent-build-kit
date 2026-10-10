"""Show the cards the units call for and clear the ones they no longer do."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from agent_build_kit import telemetry
from agent_build_kit.config import NotificationProvider, NotificationsConfig
from agent_build_kit.notify.cards import Card, desired_cards
from agent_build_kit.notify.provider import Notifier
from agent_build_kit.notify.store import Entry, NotificationStore
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.unit_store import StoredUnit


def reconcile(
    units: Sequence[StoredUnit],
    *,
    store: NotificationStore,
    notifier: Notifier,
    config: NotificationsConfig,
    log: Callable[[str], None],
) -> None:
    """Bring the shown cards to the ones `units` call for. A provider that fails is logged
    and counted, never raised; the card is tried again at the next call."""
    if config.provider is NotificationProvider.OFF:
        return

    def attempt(action: str, id: str, call: Callable[[], None]) -> bool:
        try:
            call()
        except Exception as error:  # noqa: BLE001
            log(f"notification {action} failed for {id} — {type(error).__name__}: {error}")
            telemetry.count("abk.notifications", action=action, outcome="failed")
            return False
        telemetry.count("abk.notifications", action=action, outcome="ok")
        return True

    def sound(card: Card) -> bool:
        return attempt(
            "show", card.id, lambda: notifier.show(card.id, card.title, card.body, card.link)
        )

    delay = timedelta(minutes=config.delay_minutes)
    remind = timedelta(minutes=config.remind_after_minutes)
    with store.locked():
        now = spans.clock.now()
        wanted = {card.id: card for card in desired_cards(units)}
        kept: dict[str, Entry] = {}
        for id, entry in store.entries().items():
            if id in wanted:
                kept[id] = entry
            elif entry.sounded_at is not None and not attempt(
                "clear", id, lambda id=id: notifier.clear(id)
            ):
                kept[id] = entry
        for id, card in wanted.items():
            entry = kept.get(id) or Entry(pending_since=now)
            if _due(entry, now, delay=delay, remind=remind) and sound(card):
                entry = entry.model_copy(update={"sounded_at": now})
            kept[id] = entry
        store.save(kept)


def _due(entry: Entry, now: datetime, *, delay: timedelta, remind: timedelta) -> bool:
    """Whether a card is to be sounded now: first once it has waited out the delay, then
    again each reminder interval."""
    if entry.sounded_at is None:
        return now - entry.pending_since >= delay
    return now - entry.sounded_at >= remind
