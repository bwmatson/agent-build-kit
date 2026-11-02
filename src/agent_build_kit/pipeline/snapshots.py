"""What the outside world says, read from a snapshot with its age.

A pull request's state, an account's usage reading and the pause markers are collected
by the round and read by a build step through this module, which returns the value and
how old it is. A step that finds a snapshot too old records a refresh request and the next
round refreshes it; it does not ask the host or the usage endpoint itself.

Pull requests live where the poller records them (`prs-<repo>.json`); the other kinds are
kept in `snapshots.json`, and the requests in `refresh-requests.json`, each written whole
under its lock.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.pr_poller import PrState, state_path

if TYPE_CHECKING:
    from agent_build_kit.pipeline.usage_guard import UsageReading

PR = "pr"
USAGE = "usage"
PAUSES = "pauses"

STORE = "snapshots.json"
REQUESTS = "refresh-requests.json"
WAKE = "wake"

# Told the key of what to refresh (a repo, an account, or None), it returns the new value.
Collector = Callable[[str | None], object]


class Snapshot[T](Frozen):
    """A value and when it was collected; all None when nothing has been collected."""

    value: T | None = None
    collected_at: datetime | None = None
    age: timedelta | None = None


class PullRequestState(Frozen):
    """What a snapshot holds of one pull request."""

    state: str
    mergeable: bool | None = None
    checks: dict[str, str] = {}
    labels: tuple[str, ...] = ()


class Pauses(Frozen):
    """The pause markers: when each paused unit may resume, by unit id."""

    resume_at: dict[str, datetime] = {}


class Request(Frozen):
    """One request for a refresh, by kind and key."""

    kind: str
    key: str | None = None


def _aged[T](value: T | None, collected_at: datetime | None) -> Snapshot[T]:
    if value is None or collected_at is None:
        return Snapshot()
    return Snapshot(value=value, collected_at=collected_at, age=spans.clock.now() - collected_at)


def _load(path: Path) -> object:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _write(path: Path, body: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(body, indent=2) + "\n")


def _lock(state_dir: Path, name: str):
    state_dir.mkdir(parents=True, exist_ok=True)
    return file_lock(state_dir / f"{name}.lock")


def _stored(state_dir: Path) -> dict[str, dict[str, dict]]:
    body = _load(state_dir / STORE)
    return body if isinstance(body, dict) else {}


def _entry(state_dir: Path, kind: str, key: str | None) -> tuple[dict | None, datetime | None]:
    found = _stored(state_dir).get(kind, {}).get(key or "")
    if not isinstance(found, dict):
        return None, None
    try:
        return found["value"], datetime.fromisoformat(found["collected_at"])
    except (KeyError, TypeError, ValueError):
        return None, None


def pr(state_dir: Path, repo: str, number: int) -> Snapshot[PullRequestState]:
    """The pull request as the poller last recorded it for `repo`, and how long ago."""
    path = state_path(state_dir, repo)
    seen = PrState.load(path).get(str(number))
    if not isinstance(seen, dict):
        return Snapshot()
    return _aged(
        PullRequestState(
            state=seen.get("state", "open"),
            mergeable=seen.get("mergeable"),
            checks=seen.get("checks") or {},
            labels=tuple(seen.get("labels") or ()),
        ),
        PrState.collected_at(path),
    )


def usage(state_dir: Path, account: str | None) -> Snapshot[UsageReading]:
    from agent_build_kit.pipeline.usage_guard import UsageReading

    raw, collected_at = _entry(state_dir, USAGE, account)
    return _aged(UsageReading.model_validate(raw) if raw is not None else None, collected_at)


def pauses(state_dir: Path) -> Snapshot[Pauses]:
    raw, collected_at = _entry(state_dir, PAUSES, None)
    return _aged(Pauses.model_validate(raw) if raw is not None else None, collected_at)


def requested(state_dir: Path) -> list[Request]:
    body = _load(state_dir / REQUESTS)
    if not isinstance(body, list):
        return []
    return [Request.model_validate(each) for each in body if isinstance(each, dict)]


def request_refresh(state_dir: Path, kind: str, key: str | None = None) -> None:
    """Ask the next round to refresh `kind` for `key`; asking twice records one request."""
    with _lock(state_dir, REQUESTS):
        held = requested(state_dir)
        asked = Request(kind=kind, key=key)
        if asked not in held:
            _write(state_dir / REQUESTS, [each.model_dump() for each in [*held, asked]])
    (state_dir / WAKE).touch()


def _pr_ages(state_dir: Path) -> dict[str, datetime]:
    found = {}
    for path in state_dir.glob("prs-*.json"):
        if (at := PrState.collected_at(path)) is not None:
            found[path.name.removeprefix("prs-").removesuffix(".json")] = at
    return found


def _ages(state_dir: Path, kind: str) -> dict[str | None, datetime]:
    if kind == PR:
        return {**_pr_ages(state_dir)}
    ages: dict[str | None, datetime] = {}
    for key in _stored(state_dir).get(kind, {}):
        _, at = _entry(state_dir, kind, key or None)
        if at is not None:
            ages[key or None] = at
    return ages


def _keep(state_dir: Path, kind: str, key: str | None, value: object) -> None:
    dumped = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    with _lock(state_dir, STORE):
        body = _stored(state_dir)
        body.setdefault(kind, {})[key or ""] = {
            "value": dumped,
            "collected_at": spans.clock.now().isoformat(),
        }
        _write(state_dir / STORE, body)


def run_round(
    state_dir: Path, collectors: Mapping[str, Collector], max_age: Mapping[str, timedelta]
) -> None:
    """Refresh what was requested or is over its limit, for each kind with a collector, and
    clear the requests it handled. A pull-request collector records its own snapshot (the
    poller writes the file); the others' answers are kept here."""
    asked = requested(state_dir)
    now = spans.clock.now()
    for kind, collect in collectors.items():
        keys = {each.key for each in asked if each.kind == kind}
        if (limit := max_age.get(kind)) is not None:
            keys |= {key for key, at in _ages(state_dir, kind).items() if now - at > limit}
        for key in keys:
            value = collect(key)
            if kind != PR:
                _keep(state_dir, kind, key, value)
    with _lock(state_dir, REQUESTS):
        # Only what this round read: a request made meanwhile waits for the next.
        handled = [each for each in asked if each.kind in collectors]
        left = [each for each in requested(state_dir) if each not in handled]
        _write(state_dir / REQUESTS, [each.model_dump() for each in left])
