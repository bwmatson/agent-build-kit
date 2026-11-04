"""What writes a code host's marker (spec: git-host-outage): a unit parking because a git push the
host refused or could not reach, and a fetch the host refused, which does not park its unit.

A forge API outage (`HostUnavailable` from the resilient forge) is the API host's, not the git
remote's, so it parks as before and writes no marker."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges.transport import HostUnavailable
from agent_build_kit.pipeline import pause, wiring
from agent_build_kit.pipeline.git_output import TransportFailure
from agent_build_kit.pipeline.network_probe import Reachability
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.runtimes import NetworkUnavailable
from tests.code_host_fixtures import GITHUB, GITHUB_URL, REFUSED, give_remote
from tests.conftest import make_installation
from tests.factories import unit
from tests.fake_clock import FakeClock, install
from tests.pipeline.test_network_outage_parking import UNIT, Probe, build_once, fresh_store

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Probe:
    return Probe(monkeypatch)


def raising(error: Exception):
    def push(branch: str, *, cwd: Path) -> str:
        raise error

    return push


def test_a_unit_parked_at_a_push_the_host_refused_writes_its_hosts_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    give_remote(inst, "app", GITHUB_URL)
    store = fresh_store(tmp_path)

    build_once(tmp_path, monkeypatch, store, push=raising(HostUnavailable("git push", REFUSED, 1)))

    assert store.get(UNIT).state == PLANNED
    marker = pause.host_outage(inst.state_dir, GITHUB)
    assert marker is not None
    assert (marker.repo, marker.since, marker.failed_probes) == ("app", clock.now(), 0)
    assert "Permission denied (publickey)" in marker.last_error


def test_a_push_that_could_not_reach_the_host_writes_it_when_the_control_group_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe, clock: FakeClock
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    give_remote(inst, "app", GITHUB_URL)
    probe.answer = Reachability(api=False, control=True)
    store = fresh_store(tmp_path)
    error = NetworkUnavailable(
        "Connection timed out", strength="weak", host=GITHUB, port=22, service="code_host"
    )

    build_once(tmp_path, monkeypatch, store, push=raising(error))

    assert store.get(UNIT).cause == "host_unavailable"
    assert pause.host_outage(inst.state_dir, GITHUB) is not None


def test_a_network_that_is_down_writes_the_network_pause_and_no_host_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe, clock: FakeClock
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    give_remote(inst, "app", GITHUB_URL)
    probe.answer = Reachability(api=False, control=False)
    store = fresh_store(tmp_path)
    error = NetworkUnavailable(
        "Connection timed out", strength="weak", host=GITHUB, port=22, service="code_host"
    )

    build_once(tmp_path, monkeypatch, store, push=raising(error))

    assert store.get(UNIT).cause == "network_unavailable"
    assert pause.network_pause(inst.state_dir) is not None
    assert pause.host_outages(inst.state_dir) == []


def test_a_forge_api_outage_parks_as_before_and_writes_no_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    give_remote(inst, "app", GITHUB_URL)
    store = fresh_store(tmp_path)

    build_once(
        tmp_path,
        monkeypatch,
        store,
        push=raising(HostUnavailable("create_pr", "HTTP 503", 3)),
    )

    assert store.get(UNIT).cause == "host_unavailable"
    assert pause.host_outages(inst.state_dir) == []


def test_a_repo_with_no_remote_parks_and_writes_no_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    store = fresh_store(tmp_path)

    build_once(tmp_path, monkeypatch, store, push=raising(HostUnavailable("git push", REFUSED, 1)))

    assert store.get(UNIT).state == PLANNED
    assert pause.host_outages(inst.state_dir) == []


@pytest.mark.parametrize("kind", ["refused", "unreachable"])
def test_a_fetch_the_host_failed_writes_the_marker_and_parks_nothing(
    tmp_path: Path, clock: FakeClock, kind: str
) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    give_remote(inst, "app", GITHUB_URL)
    store = fresh_store(tmp_path)
    said: list[str] = []
    note = wiring.build_note_host_outage(inst, log=said.append)

    note(unit(), TransportFailure(kind=kind, message=REFUSED))  # type: ignore[arg-type]

    marker = pause.host_outage(inst.state_dir, GITHUB)
    assert marker is not None and marker.last_error == REFUSED
    assert store.get(UNIT).state == "planned" and store.get(UNIT).cause is None


def test_a_fetch_noted_again_keeps_the_marker_it_has(tmp_path: Path, clock: FakeClock) -> None:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    give_remote(inst, "app", GITHUB_URL)
    note = wiring.build_note_host_outage(inst, log=lambda line: None)
    note(unit(), TransportFailure(kind="refused", message="first"))
    began = clock.now()
    clock.advance(30)

    note(unit(), TransportFailure(kind="refused", message="second"))

    marker = pause.host_outage(inst.state_dir, GITHUB)
    assert marker is not None and (marker.since, marker.last_error) == (began, "second")


def test_the_real_runner_notes_a_fetch_outage_in_the_marker(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wire level: the runner `build_runner` assembles has the seam set, and the seam writes the
    marker of the unit's repo's host."""
    inst = make_installation(tmp_path / "planning", planning={"state_dir": "."})
    give_remote(inst, "app", GITHUB_URL)
    runner = wiring.build_runner(
        unit(),
        store=fresh_store(tmp_path),
        installation=inst,
        log=lambda _: None,
    )

    assert runner.note_host_outage is not None
    runner.note_outage(unit(), TransportFailure(kind="refused", message=REFUSED))

    assert pause.host_outage(inst.state_dir, GITHUB) is not None
