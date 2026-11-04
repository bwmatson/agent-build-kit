"""Pausing when the usage window runs low, and coming back.

`usage_guard` decides whether a unit may start. This is what happens when it
says no (docs/architecture.md).

The way back is the tick itself. The timer runs it every few minutes whether or
not anything is paused, so a pause needs no resume of its own: each tick asks
the guard again, and the first one it allows clears the marker. That also makes
a pause answer to what changed since it was written — a threshold raised by
hand, or the ramp towards the reset offering room — instead of sleeping to a
deadline worked out before either. A separate transient timer used to be
scheduled per pause, and ignored both.

A refusal from the model itself (a rate limit) is different: its reset comes
from the API, and asking the usage endpoint instead can say there is room when
there is not. That kind of pause is honoured until its deadline.

It is also deliberately visible. A marker file plus a run-log line means the
state reads as "paused until 20:51 because the weekly window is at 92%",
rather than "idle since lunchtime for reasons unknown".
"""

from __future__ import annotations

import json
import re
import sys
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from agent_build_kit import claude_account
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.unit_store import PARK_BACKOFF

# The marker's file name in the state directory: the default account's. A named account keeps its
# own beside it, as the usage cache is kept (`claude_account.file_for`).
PAUSE_MARKER = "paused.json"

# The network outage's marker: one for the whole installation, apart from every account's.
NETWORK_MARKER = "network-paused.json"

# A code host's marker, one for each host, beside the network's: `code-host-paused.<host>.json`.
CODE_HOST_MARKER = "code-host-paused"

# Just after the reset, never exactly on it: a resume racing the window
# boundary finds it still full and pauses again.
RESUME_GRACE = timedelta(minutes=2)

# When the reset time is unknown, try again on this cadence rather than
# waiting for a human.
UNKNOWN_RETRY = timedelta(minutes=30)

# The guard's own refusal, re-checked every tick; or the model's, kept to its
# deadline; or the network being down, ended by the first tick whose probe reaches a
# control host, whatever its deadline.
PauseKind = Literal["usage", "rate_limit", "network"]


class Pause(Frozen):
    until: datetime
    reason: str
    kind: PauseKind = "usage"
    # The label of the named account the pause belongs to, read from the marker's file name; None
    # is the default account's, which a marker written before accounts were kept apart is.
    account: str | None = None


def pause_marker(state_dir: Path, account: claude_account.Account) -> Path:
    """The marker of `account`'s pause in `state_dir`; the default account's is `PAUSE_MARKER`.
    A network outage has `network_marker` of its own, never this."""
    return claude_account.file_for(state_dir / PAUSE_MARKER, account)


def _account_of(marker: Path) -> str | None:
    """The label a marker's file name carries (`paused.<label>.json`); None for `paused.json`."""
    stem, suffix = Path(PAUSE_MARKER).stem, Path(PAUSE_MARKER).suffix
    name = marker.name
    if name == PAUSE_MARKER or not (name.startswith(f"{stem}.") and name.endswith(suffix)):
        return None
    return name[len(stem) + 1 : -len(suffix)] or None


def _locked(marker: Path) -> AbstractContextManager[None]:
    """The lock every change to a marker is made under; reading takes none."""
    return file_lock(marker.with_name(f"{marker.name}.lock"))


def is_paused(marker: Path) -> Pause | None:
    """The current pause, if one is still in force.

    A pause whose deadline has passed is treated as over even if the scheduled
    resume never fired — a reboot or a disabled timer shouldn't strand the
    pipeline. An unreadable marker is treated as "not paused": unlike the unit
    store, guessing wrong here costs one usage check, not rebuilt work.
    """
    try:
        data = json.loads(marker.read_text())
        until = datetime.fromisoformat(data["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return None

    kind: PauseKind = "usage"
    if data.get("kind") in ("rate_limit", "network"):
        kind = data["kind"]
    if until <= datetime.now(UTC) and kind != "network":
        return None
    # The file name says whose pause it is; the record's own `account` only repeats it.
    return Pause(
        until=until, reason=str(data.get("reason", "")), kind=kind, account=_account_of(marker)
    )


def network_marker(state_dir: Path) -> Path:
    """The marker of a network outage: the whole installation's, in a file of its own so that no
    account's pause can replace it or be replaced by it."""
    return state_dir / NETWORK_MARKER


def network_pause(state_dir: Path) -> Pause | None:
    """The network pause in force: its own marker's, else a `paused.json` of kind `network` left
    by a version that kept every pause in one file."""
    held = is_paused(network_marker(state_dir))
    if held is not None:
        return held
    legacy = is_paused(state_dir / PAUSE_MARKER)
    return legacy if legacy is not None and legacy.kind == "network" else None


def pauses_in_force(state_dir: Path) -> list[Pause]:
    """Every pause in force in `state_dir`: the network's, then the default account's, then the
    named accounts'."""
    markers = sorted(state_dir.glob(f"{Path(PAUSE_MARKER).stem}*.json"))
    markers.sort(key=lambda marker: marker.name != PAUSE_MARKER)
    network = network_pause(state_dir)
    found = [network] if network is not None else []
    for marker in markers:
        if (held := is_paused(marker)) is not None and held.kind != "network":
            found.append(held)
    return found


def pause_for(state_dir: Path, account: claude_account.Account) -> Pause | None:
    """The pause in force for `account`'s units: its own, or a network outage, which is every
    account's."""
    return network_pause(state_dir) or is_paused(pause_marker(state_dir, account))


def pause_in_force(state_dir: Path) -> bool:
    """Whether a pause of any account is in force in `state_dir`, for what only shows it."""
    return bool(pauses_in_force(state_dir))


def every_account_paused(inst: Installation) -> bool:
    """Whether no account in use can start a build: a network outage, or a pause in force for
    each account the repos run on (the default account alone when none is named)."""
    if network_pause(inst.state_dir) is not None:
        return True
    return all(
        pause_for(inst.state_dir, account) is not None
        for account in claude_account.in_use(inst.config)
    )


def paused_or_refused(command: str, inst: Installation, why: str) -> bool:
    """Whether every account is paused (`every_account_paused`); when not, say `command` refuses,
    for `why`: a run of an account that is not paused may be writing the store."""
    if every_account_paused(inst):
        return True
    print(
        f"{command}: refused; {why}, so pause the pipeline first (nothing was changed)",
        file=sys.stderr,
    )
    return False


def resume_deadline(until: datetime | None, *, now: datetime | None = None) -> datetime:
    """When a pause ends: the grace past `until`, added here and nowhere else.

    A reset time that is not in the future is unknown, so a pause is never
    written already over.
    """
    now = now or datetime.now(UTC)
    if until is None or until <= now:
        return now + UNKNOWN_RETRY
    return until + RESUME_GRACE


def pause_until(
    until: datetime | None,
    *,
    reason: str,
    marker: Path,
    kind: PauseKind = "usage",
    account: str | None = None,
) -> Pause:
    """Record a pause: until when, why, what kind, and the label of the account it belongs to.

    A usage pause replaces the one before it, sooner or later: it is the guard's
    latest answer, and the one before was worked out from an older reading. A
    rate-limit pause is never shortened — not by another, and not by a usage
    pause, since the usage endpoint can show room the model has just refused.
    """
    return record_pause(
        Pause(until=resume_deadline(until), reason=reason, kind=kind, account=account),
        marker=marker,
    )


def record_pause(pause: Pause, *, marker: Path) -> Pause:
    """Record a pause whose deadline is already worked out, with no grace added again: the
    rules of `pause_until` hold, and it is what `pause_until` records through."""
    deadline, reason, kind, account = pause.until, pause.reason, pause.kind, pause.account

    # Read, compared and written under one lock: builds record pauses from
    # threads, and a round clearing one must not interleave with them.
    with _locked(marker):
        existing = is_paused(marker)
        if existing and existing.kind == "rate_limit" and existing.until > deadline:
            return existing
        # One network pause per outage: a later parking does not push its time out.
        if existing and existing.kind == "network" and kind == "network":
            return existing

        # Written aside and renamed into place, as `is_paused` reads without
        # the lock and a torn file would read as "not paused".
        record = {
            "until": deadline.isoformat(),
            "reason": reason,
            "kind": kind,
            "at": datetime.now(UTC).isoformat(),
        }
        if account is not None:
            record["account"] = account
        atomic_write_text(marker, json.dumps(record, indent=2) + "\n")
    return Pause(until=deadline, reason=reason, kind=kind, account=account)


def pause_line(pause: Pause, *, verb: str = "paused", now: datetime | None = None) -> str:
    """The run-log line announcing a pause: its end in local time, and why.

    The end is never shown earlier than `now`, the moment the line is printed.
    """
    if pause.kind == "network":
        return f"waiting for the network — {pause.reason}"
    now = now or datetime.now(UTC)
    end = max(pause.until, now).astimezone()
    return f"{verb} until {end:%H:%M} — {pause.reason}"


def clear_pause(marker: Path) -> Pause | None:
    """End a pause the guard has found room under.

    A network pause is left alone and not returned: only the probe ends it, and
    what holds a round is the pause the caller read, not this one. A rate-limit
    pause in force is left alone and returned: it is the model's
    refusal, kept to its deadline, and the caller's own reading said none held,
    so a build has recorded it since. Clearing it would let the pass start
    builds the model has just refused. None means the marker was cleared, or
    there was nothing to clear.
    """
    with _locked(marker):
        held = is_paused(marker)
        if held and held.kind == "rate_limit":
            return held
        if held and held.kind == "network":
            return None
        marker.unlink(missing_ok=True)
    return None


def end_network_pause(state_dir: Path) -> bool:
    """End a network pause because the network is back; whether there was one. Every account's
    own pause is left as it was."""
    ended = False
    for marker in (network_marker(state_dir), state_dir / PAUSE_MARKER):
        with _locked(marker):
            held = is_paused(marker)
            if held is not None and held.kind == "network":
                marker.unlink(missing_ok=True)
                ended = True
    return ended


# --- the code host's marker --------------------------------------------------------------------


class HostOutage(Frozen):
    """One code host that refused or could not be reached, and what is known of it.

    Keyed by the host of a repo's push remote, so it pauses the repos on that host and no other.
    `repo` is the repo whose checkout the probe runs from. `last_checked` is the last probe, or
    the failure that wrote the marker before the first; `failed_probes` counts the probes that
    failed in a row. A marker a passing probe ended is kept with `cleared_at`, which is how every
    unit that parked before it knows its own backoff is over; it is in force only without one.
    """

    host: str
    repo: str
    since: datetime
    last_error: str
    last_checked: datetime
    failed_probes: int = 0
    cleared_at: datetime | None = None

    @property
    def in_force(self) -> bool:
        return self.cleared_at is None

    def wait(self) -> timedelta:
        """How long after `last_checked` the next probe may be made: the park ladder, a step
        up for each probe that failed."""
        return PARK_BACKOFF[min(self.failed_probes, len(PARK_BACKOFF) - 1)]

    def probe_due(self, now: datetime) -> bool:
        return now >= self.last_checked + self.wait()

    def down_for(self, now: datetime) -> timedelta:
        return max(now - self.since, timedelta(0))


def code_host_marker(state_dir: Path, host: str) -> Path:
    """The marker of `host` in `state_dir`; anything in a host name a file name cannot hold is
    replaced."""
    return state_dir / f"{CODE_HOST_MARKER}.{re.sub(r'[^A-Za-z0-9.-]', '_', host)}.json"


def _read_host(marker: Path) -> HostOutage | None:
    try:
        return HostOutage.model_validate_json(marker.read_text())
    except (OSError, ValueError):
        return None


def _write_host(marker: Path, outage: HostOutage) -> None:
    atomic_write_text(marker, outage.model_dump_json(indent=2) + "\n")


def host_outage(state_dir: Path, host: str) -> HostOutage | None:
    """The marker of `host` when it is in force. An unreadable one counts as none, as the other
    markers do: guessing wrong costs one probe."""
    held = _read_host(code_host_marker(state_dir, host))
    return held if held is not None and held.in_force else None


def host_outages(state_dir: Path) -> list[HostOutage]:
    """Every code host's marker in force in `state_dir`, by host."""
    found = (_read_host(marker) for marker in sorted(state_dir.glob(f"{CODE_HOST_MARKER}.*.json")))
    return [held for held in found if held is not None and held.in_force]


def host_released_at(state_dir: Path, host: str) -> datetime | None:
    """When a passing probe last ended `host`'s marker, or None when it never has."""
    held = _read_host(code_host_marker(state_dir, host))
    return held.cleared_at if held is not None else None


def note_host_outage(
    state_dir: Path, host: str, *, repo: str, error: str, now: datetime
) -> HostOutage:
    """Record that `host` refused or could not be reached, for `repo`: a unit parking, or a fetch.

    A marker in force keeps when it began and its probes and takes the new error; one that a
    probe ended, or none, is a new outage.
    """
    marker = code_host_marker(state_dir, host)
    with _locked(marker):
        held = _read_host(marker)
        if held is not None and held.in_force:
            noted = held.model_copy(update={"last_error": error})
        else:
            noted = HostOutage(host=host, repo=repo, since=now, last_error=error, last_checked=now)
        _write_host(marker, noted)
    return noted


def record_host_probe(
    state_dir: Path, host: str, *, healthy: bool, error: str, now: datetime
) -> HostOutage | None:
    """Record a probe of `host`: a pass ends the marker (and returns None), a failure counts and
    lengthens the wait. None too when there is no marker in force to record it on."""
    marker = code_host_marker(state_dir, host)
    with _locked(marker):
        held = _read_host(marker)
        if held is None or not held.in_force:
            return None
        if healthy:
            _write_host(marker, held.model_copy(update={"cleared_at": now, "failed_probes": 0}))
            return None
        failed = held.model_copy(
            update={
                "failed_probes": held.failed_probes + 1,
                "last_checked": now,
                "last_error": error or held.last_error,
            }
        )
        _write_host(marker, failed)
    return failed
