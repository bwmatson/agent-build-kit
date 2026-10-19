"""The decision log: why each unit that is not running is waiting, written when it changes."""

from __future__ import annotations

import json
from collections.abc import Callable, Collection, Mapping
from datetime import datetime
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.vocabulary import WaitReason

# The decision log, in the state directory.
DECISIONS_NAME = "decisions.jsonl"

# The reason a closing record carries.
ENDED = "none"

# The waits that become a span when they end. `slot` and `usage_pause` are spans
# already, written where the unit starts or resumes, and a second would count the
# time twice.
SPANNED = frozenset(
    {WaitReason.QUEUE_FULL, WaitReason.LEASE, WaitReason.BACKOFF, WaitReason.NEEDS_PERSON}
)


class Wait(Frozen):
    """A unit's reason for not running, and the units it waits on."""

    reason: WaitReason
    waits_on: tuple[str, ...] = ()
    # What the reason reads in words, when the reason alone does not say it.
    detail: str = ""


def recorded_waits(path: Path) -> dict[str, tuple[Wait, datetime]]:
    """Each unit the log at `path` last recorded as waiting, with the wait and since when; a
    unit whose last record closed its wait is not in it."""
    current: dict[str, tuple[Wait, datetime]] = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return current
    for line in lines:
        try:
            raw = json.loads(line)
            unit = str(raw["unit"])
            if raw["reason"] == ENDED:
                current.pop(unit, None)
                continue
            wait = Wait(reason=WaitReason(raw["reason"]), waits_on=tuple(raw["waits_on"]))
            current[unit] = (wait, datetime.fromisoformat(raw["at"]))
        except (ValueError, KeyError, TypeError):
            continue
    return current


class WaitRecorder:
    """Appends `{at, unit, reason, waits_on, tick}` to the log at `path` only when a
    unit's reason or what it waits on changes, resuming from the log's tail."""

    def __init__(self, path: Path, say: Callable[[str], None]) -> None:
        self.path = path
        self.say = say
        self._told = False
        # Each waiting unit: what it waits for, and since when.
        self._current: dict[str, tuple[Wait, datetime]] = self._resume()

    def _resume(self) -> dict[str, tuple[Wait, datetime]]:
        return recorded_waits(self.path)

    def record(self, waits: Mapping[str, Wait], *, tick: str, keep: Collection[str] = ()) -> None:
        """Log what changed since the last call; a unit that left `waits` gets a
        closing record (unless it is in `keep`: a unit this pass did not look at, whose wait
        goes on), and a wait that ended a span if it is one the build path does
        not write."""
        now = spans.clock.now()
        for unit, wait in waits.items():
            before = self._current.get(unit)
            if before and (before[0].reason, before[0].waits_on) == (wait.reason, wait.waits_on):
                # The detail is words for a reader; a change in it is not a new wait.
                continue
            if before:
                self._end(unit, before)
            self._current[unit] = (wait, now)
            self._append(now, unit, wait.reason, wait.waits_on, tick)
        for unit in [unit for unit in self._current if unit not in waits and unit not in keep]:
            self._end(unit, self._current.pop(unit))
            self._append(now, unit, ENDED, (), tick)

    def _end(self, unit: str, before: tuple[Wait, datetime]) -> None:
        wait, since = before
        if wait.reason in SPANNED:
            spans.record_span(
                spans.Mark(since),
                self.say,
                unit=unit,
                change=unit.partition("/")[0],
                waited=wait.reason.value,
            )

    def _append(
        self, at: datetime, unit: str, reason: str, waits_on: tuple[str, ...], tick: str
    ) -> None:
        line = {
            "at": at.isoformat(),
            "unit": unit,
            "reason": str(reason),
            "waits_on": list(waits_on),
            "tick": tick,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as log:
                log.write(json.dumps(line) + "\n")
        except OSError as error:
            if not self._told:
                self._told = True
                self.say(f"the decision log could not be written: {error}")


# What a trim leaves, as a share of the limit, so the next rewrite waits for that much growth.
TRIM_TO = 0.8


def trim_decision_log(path: Path, *, limit_mb: float) -> None:
    """Drop the oldest lines of the log at `path` once it passes `limit_mb` megabytes, down to
    `TRIM_TO` of the limit. A diagnostic file: a failure to rewrite it leaves it as it was."""
    limit = int(limit_mb * 1024 * 1024)
    try:
        if path.stat().st_size <= limit:
            return
        lines = path.read_bytes().splitlines(keepends=True)
    except OSError:
        return
    kept: list[bytes] = []
    size = 0
    for line in reversed(lines):
        if size + len(line) > limit * TRIM_TO:
            break
        kept.append(line)
        size += len(line)
    try:
        atomic_write_text(path, b"".join(reversed(kept)).decode(errors="replace"))
    except (OSError, UnicodeError):
        pass
