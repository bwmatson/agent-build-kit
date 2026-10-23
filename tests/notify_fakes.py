"""A recording `Notifier`, and the rounds the notification tests drive."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from agent_build_kit.config import NotificationProvider, NotificationsConfig
from agent_build_kit.notify.reconcile import reconcile
from agent_build_kit.notify.store import NotificationStore
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import MERGED
from tests.factories import stored_unit
from tests.fake_clock import FakeClock


class FakeNotifier:
    """Records every call; a call fails while its `fail_*` flag is set."""

    def __init__(self) -> None:
        self.shown: list[tuple[str, str, str, str]] = []
        self.cleared: list[str] = []
        self.show_attempts = 0
        self.clear_attempts = 0
        self.fail_show = False
        self.fail_clear = False
        self._lock = threading.Lock()

    def show(self, id: str, title: str, body: str, link: str) -> None:
        with self._lock:
            self.show_attempts += 1
        if self.fail_show:
            raise RuntimeError("the provider is down")
        with self._lock:
            self.shown.append((id, title, body, link))

    def clear(self, id: str) -> None:
        with self._lock:
            self.clear_attempts += 1
        if self.fail_clear:
            raise RuntimeError("the provider is down")
        with self._lock:
            self.cleared.append(id)

    @property
    def shown_ids(self) -> list[str]:
        return [shown[0] for shown in self.shown]


def enabled(**overrides) -> NotificationsConfig:
    """A provider that is on, with no delay unless a test sets one."""
    return NotificationsConfig.model_validate(
        {
            "provider": NotificationProvider.COMMAND,
            "command": {"show": "notify {id}", "clear": "dismiss {id}"},
            "delay_minutes": 0,
            **overrides,
        }
    )


def landed_unit(uid: str, at: datetime, *, pr: int = 7) -> StoredUnit:
    """A unit the pipeline landed without a person at `at`."""
    history = ({"state": MERGED, "at": at.isoformat(), "cause": Cause.AUTO_LANDED.value},)
    return stored_unit(uid, state=MERGED, pr=pr, history=history)


class Rounds:
    """Reconciles units against one notifier and one state file, a fake clock apart."""

    def __init__(
        self,
        path: Path,
        clock: FakeClock,
        config: NotificationsConfig,
        notifier: FakeNotifier | None = None,
    ) -> None:
        self.path = path
        self.clock = clock
        self.config = config
        self.notifier = notifier or FakeNotifier()
        self.lines: list[str] = []

    def store(self) -> NotificationStore:
        """A store read afresh from the file, as a new process would."""
        return NotificationStore(self.path)

    def tick(self, units: Sequence[StoredUnit], *, minutes: float = 0) -> None:
        self.clock.advance(minutes * 60)
        reconcile(
            units,
            store=self.store(),
            notifier=self.notifier,
            config=self.config,
            log=self.lines.append,
        )
