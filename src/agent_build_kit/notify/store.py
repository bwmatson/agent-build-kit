"""`notifications.json`: which cards are called for, and when each was sounded."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_build_kit.model import Frozen


class Entry(Frozen):
    pending_since: datetime
    # None until a provider has accepted the card.
    sounded_at: datetime | None = None


class NotificationStore:
    def __init__(self, path: Path) -> None:
        raise NotImplementedError

    def entries(self) -> dict[str, Entry]:
        raise NotImplementedError
