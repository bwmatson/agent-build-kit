"""Show the cards the units call for and clear the ones they no longer do."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agent_build_kit.config import NotificationsConfig
from agent_build_kit.notify.provider import Notifier
from agent_build_kit.notify.store import NotificationStore
from agent_build_kit.pipeline.unit_store import StoredUnit


def reconcile(
    units: Sequence[StoredUnit],
    *,
    store: NotificationStore,
    notifier: Notifier,
    config: NotificationsConfig,
    log: Callable[[str], None],
) -> None:
    raise NotImplementedError
