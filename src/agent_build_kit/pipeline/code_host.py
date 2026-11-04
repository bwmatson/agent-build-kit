"""The code host's marker, read and kept (docs/architecture.md, "The code host outage").

A git push the host refuses or cannot reach parks its unit, and a fetch it refuses is noted.
Both write one marker for the host of the repo's push remote (`pause.HostOutage`). Each refresh of
a pass makes at most one authenticated probe of each marker (`network_probe.code_host_healthy`),
so the units waiting on it make none of their own: a unit parked for the host waits while the
marker holds, and starts with the rest the pass in which a probe passes. While a marker holds, no
unit of a repo on that host starts; a repo on another host is not touched.

Time is `spans.clock`, so a test moves it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import network_probe, pause, shell, spans
from agent_build_kit.pipeline.restack import remote_endpoint
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, backoff_remaining
from agent_build_kit.pipeline.units import PLANNED

# What a unit's status says it waits for, with the host after it.
WAITING = "waiting for the code host"

# The longest a marker's last error is kept: git can print a page.
ERROR_LENGTH = 400


class Refreshed(Frozen):
    """What one refresh did: the hosts probed, and those whose marker a passing probe ended."""

    probed: tuple[str, ...] = ()
    cleared: tuple[str, ...] = ()


def host_of(checkout: Path) -> str | None:
    """The host of the repo's push remote (`origin`'s), lower case, or None for a checkout that is
    not there, has no remote or names no host."""
    if not checkout.is_dir() or not shell.has_origin(checkout):
        return None
    url = shell.git(checkout, "remote", "get-url", "origin", check=False).stdout.strip()
    host, _ = remote_endpoint(url)
    return host.lower() or None


def host_of_repo(inst: Installation, repo: str) -> str | None:
    """`host_of` for a repo of the installation; None for a name it does not have."""
    checkout = inst.checkouts.get(repo)
    return host_of(checkout) if checkout is not None else None


def short(error: str) -> str:
    """An error as the marker keeps it: its first line, cut."""
    first = next((line.strip() for line in error.splitlines() if line.strip()), "")
    return first[:ERROR_LENGTH]


def note(inst: Installation, repo: str, error: str) -> str | None:
    """Record that the host of `repo`'s push remote refused or could not be reached; the host,
    or None when the repo has no host to name."""
    if (host := host_of_repo(inst, repo)) is None:
        return None
    pause.note_host_outage(
        inst.state_dir, host, repo=repo, error=short(error), now=spans.clock.now()
    )
    return host


class Holds(Frozen):
    """What the code hosts' markers hold, by repo, read once for a round.

    `held` maps a repo to the marker in force for its push remote's host; `cleared` maps it to
    when a passing probe last ended that host's marker.
    """

    held: dict[str, pause.HostOutage] = {}
    cleared: dict[str, datetime] = {}

    def holding(self, unit: StoredUnit) -> pause.HostOutage | None:
        """The marker that holds a planned unit back: no unit of a repo on a host whose marker is
        in force starts, new, resumed or readmitted. A unit already building is not held."""
        return self.held.get(unit.repo) if unit.state == PLANNED else None

    def released(self, unit: StoredUnit) -> bool:
        """Whether a unit parked for the code host was parked before a passing probe ended its
        host's marker, which ends its own backoff: every unit waiting on the marker starts
        together."""
        if unit.cause is not Cause.HOST_UNAVAILABLE or (parked := unit.cause_since) is None:
            return False
        cleared = self.cleared.get(unit.repo)
        return cleared is not None and parked <= cleared


def holds_of(inst: Installation) -> Holds:
    """The markers' holds, by repo. No marker file, no git asked: the common case costs a glob."""
    markers = sorted(inst.state_dir.glob(f"{pause.CODE_HOST_MARKER}.*.json"))
    if not markers:
        return Holds()
    held: dict[str, pause.HostOutage] = {}
    cleared: dict[str, datetime] = {}
    for repo in inst.repos:
        host = host_of_repo(inst, repo)
        if host is None:
            continue
        if (marker := pause.host_outage(inst.state_dir, host)) is not None:
            held[repo] = marker
        elif (ended := pause.host_released_at(inst.state_dir, host)) is not None:
            cleared[repo] = ended
    return Holds(held=held, cleared=cleared)


def backoff_left(unit: StoredUnit, now: datetime, holds: Holds) -> timedelta | None:
    """`backoff_remaining` for a unit that the markers may have released: None once its host's
    marker ended after it parked. A marker still in force holds the unit whatever this says
    (`Holds.holding`)."""
    return None if holds.released(unit) else backoff_remaining(unit, now)


def wait_text(host: str) -> str:
    return f"{WAITING} ({host})"


def refresh(inst: Installation) -> Refreshed:
    """Probe each marker in force whose wait has passed, once, and record the answer: a pass ends
    the marker, a failure counts and lengthens the wait. A refresh sooner than a marker's wait
    probes nothing, however often it is asked.

    A probe that cannot be made counts the host healthy, so a bug in it never holds work: no
    repo to ask from, or any error but a failed read.
    """
    now = spans.clock.now()
    timeout = inst.config.global_limits.network_probe_timeout_seconds
    probed: list[str] = []
    cleared: list[str] = []
    for marker in pause.host_outages(inst.state_dir):
        if not marker.probe_due(now):
            continue
        probed.append(marker.host)
        checkout = inst.checkouts.get(marker.repo)
        try:
            answer = (
                network_probe.code_host_healthy(checkout, timeout=timeout)
                if checkout is not None
                else network_probe.HostProbe(healthy=True)
            )
        except Exception:  # noqa: BLE001
            answer = network_probe.HostProbe(healthy=True)
        pause.record_host_probe(
            inst.state_dir, marker.host, healthy=answer.healthy, error=short(answer.error), now=now
        )
        if answer.healthy:
            cleared.append(marker.host)
    return Refreshed(probed=tuple(probed), cleared=tuple(cleared))


def past_limit(inst: Installation, marker: pause.HostOutage, now: datetime) -> bool:
    """Whether the marker's probes have failed for `global_limits.code_host_outage_minutes`."""
    limit = inst.config.global_limits.code_host_outage_minutes
    return marker.failed_probes > 0 and marker.down_for(now).total_seconds() >= limit * 60


def outage_text(marker: pause.HostOutage, now: datetime) -> str:
    """The code host, how long it has been down and the last error."""
    minutes = int(marker.down_for(now).total_seconds() // 60)
    return (
        f"the code host {marker.host} has been unreachable for {minutes} minutes: "
        f"{marker.last_error}"
    )


def long_outages(inst: Installation, now: datetime) -> list[pause.HostOutage]:
    """The markers in force whose outage is past the limit."""
    return [each for each in pause.host_outages(inst.state_dir) if past_limit(inst, each, now)]
