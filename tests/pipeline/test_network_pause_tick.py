"""A tick under a `network` pause starts no agent run until the control group answers.

The connect is replaced below the control-group check. The marker ends on the
first tick whose probe reaches a control host, whatever time it was given, and on nothing
else: not a deadline, and not a usage reading that allows work. Usage and rate-limit pauses
never consult the probe.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import network_probe
from agent_build_kit.pipeline.pause import pause_until
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.usage_guard import Decision
from tests.pipeline import test_cli_pipeline as base
from tests.pipeline.test_cli_pipeline import (  # noqa: F401 — fixtures
    FakeRunner,
    argv_namespace,
    healthy,
    isolated,
    stored,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")

REASON = "network unreachable during add-marker/1"


class Control:
    """The control group as the network gives it: reachable or not, and how many rounds asked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.up = False
        self.asked: list[str] = []
        real = network_probe.control_reachable

        def asked(*args: object, **kwargs: object) -> bool:
            self.asked.append("round")
            return real(*args, **kwargs)  # type: ignore[arg-type]

        def connect(host: str, port: int, timeout: float) -> object:
            if not self.up:
                raise OSError(f"cannot reach {host}")
            return None

        monkeypatch.setattr(network_probe, "resolve_name", lambda host: None)
        monkeypatch.setattr(network_probe, "connect_tcp", connect)
        monkeypatch.setattr(network_probe, "control_reachable", asked)


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Control:
    return Control(monkeypatch)


def write_marker(tmp_path: Path, *, until: datetime) -> None:
    """A `network` marker as parking writes it, with `until` as given."""
    (tmp_path / "network-paused.json").write_text(
        json.dumps(
            {
                "until": until.isoformat(),
                "reason": REASON,
                "kind": "network",
                "at": datetime.now(UTC).isoformat(),
            }
        )
    )


def tick(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """One tick that builds what it starts with a runner that only records it."""
    built: list[str] = []
    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: FakeRunner(built))
    assert cli.cmd_tick(argv_namespace(dry_run=False), base.inst) == 0
    return built


def test_a_tick_whose_control_group_is_down_starts_nothing_and_says_so_once(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe: Control,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored(), stored("add-marker/2")])
    store.set_state("add-marker/1", PLANNED, note="EAI_AGAIN", cause=Cause.NETWORK_UNAVAILABLE)
    before = store.get("add-marker/1")
    write_marker(tmp_path, until=datetime.now(UTC) + timedelta(minutes=1))

    built = tick(monkeypatch)

    assert built == []
    said = [
        line for line in capsys.readouterr().out.splitlines() if "waiting for the network" in line
    ]
    assert len(said) == 1
    assert REASON in said[0]
    assert (tmp_path / "network-paused.json").exists()
    after = store.get("add-marker/1")
    assert (after.state, after.cause, after.parked_attempts) == (
        before.state,
        before.cause,
        before.parked_attempts,
    )
    assert len(probe.asked) == 1


def test_a_marker_whose_time_has_passed_stays_while_the_control_group_is_down(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe: Control,
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])
    write_marker(tmp_path, until=datetime.now(UTC) - timedelta(hours=1))

    built = tick(monkeypatch)

    assert built == []
    assert json.loads((tmp_path / "network-paused.json").read_text())["kind"] == "network"


def test_a_reachable_control_host_clears_the_marker_whatever_its_time_and_work_starts(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe: Control,
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored(), stored("add-marker/2")])
    store.set_state("add-marker/1", PLANNED, note="HTTP 529", cause=Cause.SERVICE_UNAVAILABLE)
    probe.up = True
    pause_until(
        datetime.now(UTC) + timedelta(hours=3),
        reason=REASON,
        marker=tmp_path / "network-paused.json",
        kind="network",
    )

    built = tick(monkeypatch)

    assert built == ["add-marker/2"]
    assert not (tmp_path / "network-paused.json").exists()
    standing = store.get("add-marker/1")
    assert (standing.state, standing.cause) == (PLANNED, Cause.SERVICE_UNAVAILABLE)

    # No marker now: a unit parked for the model service does not hold the next tick back,
    # and the probe is not asked about a network nobody has reported down.
    asked = len(probe.asked)
    store.upsert([stored("add-marker/3")])

    assert "add-marker/3" in tick(monkeypatch)
    assert len(probe.asked) == asked


def test_a_usage_reading_that_allows_work_does_not_clear_the_marker(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe: Control,
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])
    write_marker(tmp_path, until=datetime.now(UTC) + timedelta(hours=1))

    assert tick(monkeypatch) == []
    assert (tmp_path / "network-paused.json").exists()
    assert len(probe.asked) == 1


@pytest.mark.parametrize("kind", ["usage", "rate_limit"])
def test_a_usage_or_rate_limit_pause_never_asks_the_probe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe: Control,
    kind: str,
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])
    monkeypatch.setattr(cli, "current_usage", lambda: base.reading(session_pct=88))
    monkeypatch.setattr(
        cli,
        "may_start_unit",
        lambda r: Decision(may_start=False, reason="session usage at 88%", resume_at=r.resets_at),
    )
    write_marker(tmp_path, until=datetime.now(UTC) + timedelta(hours=1))
    assert cli.cmd_tick(argv_namespace(dry_run=True), base.inst) == 0
    assert len(probe.asked) == 1, "the network marker is asked about first"
    probe.asked.clear()
    (tmp_path / "network-paused.json").unlink()
    pause_until(
        datetime.now(UTC) + timedelta(hours=1),
        reason="held",
        marker=tmp_path / "paused.json",
        kind=kind,  # type: ignore[arg-type]
    )

    assert cli.cmd_tick(argv_namespace(dry_run=True), base.inst) == 0

    assert probe.asked == []
    assert json.loads((tmp_path / "paused.json").read_text())["kind"] == kind


def test_status_shows_the_pause_as_waiting_for_the_network_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe: Control,
    capsys: pytest.CaptureFixture[str],
) -> None:
    UnitStore(tmp_path / "units.json").upsert([stored()])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    write_marker(tmp_path, until=datetime.now(UTC) + timedelta(hours=1))

    assert cli.cmd_status(argparse.Namespace(), base.inst) == 0

    shown = [
        line for line in capsys.readouterr().out.splitlines() if "waiting for the network" in line
    ]
    assert len(shown) == 1
    assert REASON in shown[0]
    assert probe.asked == [], "status only reads"
    assert (tmp_path / "network-paused.json").exists()


def test_a_probe_that_breaks_under_a_network_marker_ends_it_and_work_starts(
    healthy,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A lookup that raises something other than a connection failure (a host label too long
    for the resolver) cannot say the network is down, so it must not hold the pause."""

    def broken(host: str) -> object:
        raise ValueError("label too long")

    monkeypatch.setattr(network_probe, "resolve_name", broken)
    UnitStore(tmp_path / "units.json").upsert([stored()])
    write_marker(tmp_path, until=datetime.now(UTC) - timedelta(hours=1))

    built = tick(monkeypatch)

    assert built == ["add-marker/1"]
    assert not (tmp_path / "network-paused.json").exists()
