"""`notifications.json`: which cards are called for, and when each was sounded."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock


class Entry(Frozen):
    pending_since: datetime
    # None until a provider has accepted the card.
    sounded_at: datetime | None = None


class NotificationStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Hold the file against other writers: a reconciliation reads, shows and writes
        under it, so two overlapping ticks cannot both show one card."""
        with file_lock(self.path.with_name(f"{self.path.name}.lock")):
            yield

    def entries(self) -> dict[str, Entry]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text())
        return {id: Entry.model_validate(entry) for id, entry in raw["cards"].items()}

    def save(self, entries: dict[str, Entry]) -> None:
        payload = {"cards": {id: entry.model_dump(mode="json") for id, entry in entries.items()}}
        # Written aside and renamed into place: reads are not locked.
        atomic_write_text(self.path, json.dumps(payload, indent=2) + "\n")
