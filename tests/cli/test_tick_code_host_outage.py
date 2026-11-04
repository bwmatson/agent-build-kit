"""A code host's marker holds the units waiting on it (spec: git-host-outage).

While a host's marker is in force, the units parked for it make no attempt of their own, whatever
their own backoff: a pass makes one probe for the marker, and a passing probe clears it and lets
every waiting unit start in that same pass. No new unit of a repo on that host starts, a unit of a
repo on another host starts as usual, and a unit already building carries on.

Every test drives `cmd_tick` over a builder stand-in, a fake clock and a probe stand-in."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import pause
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from tests.cli.test_tick_scheduling import SEVERAL_REFRESHES, WAIT
from tests.code_host_fixtures import (
    AZURE,
    AZURE_URL,
    GITHUB,
    GITHUB_URL,
    Probe,
    give_remote,
    mark,
    park,
)
from tests.fake_clock import FakeClock, install
from tests.tick_driver import count_refreshes
from tests.tick_pass import (
    Builder,
    install_builder,
    isolate,
    stored,
    tick,
    warm_unit_graphs,
    workspace,
)
from tests.waiting import wait_for

pytestmark = pytest.mark.usefixtures("scripted_engine")

MINUTE = 60


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Probe:
    return Probe(monkeypatch)


def two_hosts(tmp_path: Path, **limits):
    """`app` on GitHub and `platform` on Azure DevOps."""
    inst = workspace(tmp_path, **limits)
    give_remote(inst, "app", GITHUB_URL)
    give_remote(inst, "platform", AZURE_URL)
    return inst


# --- the one probe, and no attempt of a unit's own ---------------------------------------------


def test_three_parked_units_make_one_probe_and_none_retries(
    tmp_path: Path, builder: Builder, clock: FakeClock, probe: Probe
) -> None:
    inst = two_hosts(tmp_path)
    for uid in ("one/1", "two/1", "three/1"):
        park(builder.store, uid)
    mark(inst, GITHUB, repo="app", now=clock.now())
    clock.advance(2 * MINUTE)  # past the wait of the marker and the backoff of each unit

    assert tick(inst) == 0

    assert probe.calls == [inst.checkouts["app"]], "one probe, not one for each unit"
    assert builder.started == [], "a parked unit retried its own step"
    assert pause.host_outage(inst.state_dir, GITHUB) is not None


def test_a_refresh_sooner_than_the_markers_wait_makes_no_probe(
    tmp_path: Path, builder: Builder, clock: FakeClock, probe: Probe
) -> None:
    inst = two_hosts(tmp_path)
    park(builder.store, "one/1")
    mark(inst, GITHUB, repo="app", now=clock.now())
    clock.advance(MINUTE)
    tick(inst)
    assert len(probe.calls) == 1

    clock.advance(2 * MINUTE - 1)  # the wait after one failed probe is two minutes
    tick(inst)
    assert len(probe.calls) == 1, "probed a second early"

    clock.advance(1)
    tick(inst)
    assert len(probe.calls) == 2
    assert builder.started == []


def test_a_unit_whose_own_backoff_is_over_waits_while_the_marker_holds(
    tmp_path: Path, builder: Builder, clock: FakeClock, probe: Probe
) -> None:
    """One minute is the unit's own backoff; the marker is a day old and the probe still fails."""
    inst = two_hosts(tmp_path)
    park(builder.store, "one/1")
    mark(inst, GITHUB, repo="app", now=clock.now())
    for _ in range(6):
        clock.advance(31 * MINUTE)
        tick(inst)

    assert builder.started == []
    assert builder.store.get("one/1").state == PLANNED


def test_a_passing_probe_clears_the_marker_and_starts_every_waiting_unit_in_that_pass(
    tmp_path: Path, builder: Builder, clock: FakeClock, probe: Probe
) -> None:
    inst = two_hosts(tmp_path)
    for uid in ("one/1", "two/1", "three/1"):
        # Five parkings in a row: thirty minutes of the unit's own backoff, none of it over.
        park(builder.store, uid, attempts=5)
    mark(inst, GITHUB, repo="app", now=clock.now())
    clock.advance(MINUTE)
    probe.healthy = True

    assert tick(inst) == 0

    assert len(probe.calls) == 1
    assert pause.host_outage(inst.state_dir, GITHUB) is None
    assert sorted(builder.started) == ["one/1", "three/1", "two/1"]
    assert all(builder.store.get(uid).state == IN_REVIEW for uid in builder.started)


def test_a_unit_parked_after_the_marker_cleared_keeps_its_own_backoff(
    tmp_path: Path, builder: Builder, clock: FakeClock, probe: Probe
) -> None:
    inst = two_hosts(tmp_path)
    park(builder.store, "first/1")
    mark(inst, GITHUB, repo="app", now=clock.now())
    clock.advance(MINUTE)
    probe.healthy = True
    tick(inst)
    assert builder.started == ["first/1"], "the marker was cleared and its unit released"
    clock.advance(1)
    park(builder.store, "late/1", attempts=5)

    clock.advance(MINUTE)
    tick(inst)

    assert builder.started == ["first/1"], "released by a marker that was cleared before it parked"


def test_a_unit_the_pass_parks_is_not_readmitted_while_the_marker_holds_it(
    tmp_path: Path,
    builder: Builder,
    clock: FakeClock,
    probe: Probe,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The running pass's readmission, beside the existing one for the unit's own backoff."""
    inst = two_hosts(tmp_path, max_concurrent=2)
    builder.store.upsert([stored("sent/1"), stored("slow/1", repo="platform")])
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    refreshes = count_refreshes(monkeypatch)
    runs: list[int] = []

    def parks_once() -> str | None:
        runs.append(1)
        if len(runs) == 1:
            mark(inst, GITHUB, repo="app", now=clock.now())
            return "held"
        return None

    builder.scripts["sent/1"] = parks_once
    builder.ends["sent/1"] = (PLANNED, Cause.HOST_UNAVAILABLE, "push: host unavailable")

    def slow() -> str | None:
        wait_for(lambda: "sent/1" in builder.finished, what="sent/1 to finish", timeout=WAIT)
        clock.advance(MINUTE + 1)  # its own backoff is over
        refreshes.wait_for(refreshes.count + SEVERAL_REFRESHES, timeout=WAIT)
        return None

    builder.scripts["slow/1"] = slow

    assert tick(inst) == 0

    assert builder.started.count("sent/1") == 1
    assert probe.calls, "the refreshes probed the host"


# --- a focused pause on new starts ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "paused", "free"),
    [(GITHUB, "new/1", "ado/1"), (AZURE, "ado/1", "new/1")],
    ids=["github-marker", "azure-marker"],
)
def test_a_marker_pauses_new_starts_of_repos_on_its_host_and_no_other(
    tmp_path: Path,
    builder: Builder,
    clock: FakeClock,
    probe: Probe,
    host: str,
    paused: str,
    free: str,
) -> None:
    inst = two_hosts(tmp_path)
    builder.store.upsert([stored("new/1"), stored("ado/1", repo="platform")])
    mark(inst, host, repo="app" if host == GITHUB else "platform", now=clock.now())

    assert tick(inst) == 0

    assert builder.started == [free]
    assert builder.store.get(paused).state == PLANNED
    assert builder.store.get(free).state == IN_REVIEW


def test_the_wait_reason_of_a_paused_unit_names_the_host(
    tmp_path: Path, builder: Builder, clock: FakeClock, probe: Probe
) -> None:
    inst = two_hosts(tmp_path)
    builder.store.upsert([stored("new/1"), stored("ado/1", repo="platform")])
    mark(inst, GITHUB, repo="app", now=clock.now())

    waits = cli.wait_reasons(
        inst, builder.store.all(), started=set(), building=set(), only=frozenset()
    )

    assert "waiting for the code host (github.com)" in waits["new/1"].detail
    assert "code host" not in waits["ado/1"].detail


def test_a_unit_already_building_carries_on_while_later_units_of_its_host_wait(
    tmp_path: Path, builder: Builder, clock: FakeClock, probe: Probe
) -> None:
    inst = two_hosts(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("build/1"), stored("later/1"), stored("ado/1", repo="platform")])
    # The unit building meets the outage: the marker is written while it builds.
    builder.scripts["build/1"] = lambda: mark(inst, GITHUB, repo="app", now=clock.now())

    assert tick(inst) == 0

    assert builder.store.get("build/1").state == IN_REVIEW, "the building unit was stopped"
    assert "later/1" not in builder.started, "a new unit started on the host that is down"
    assert "ado/1" in builder.started


def test_the_pause_ends_with_the_marker(
    tmp_path: Path, builder: Builder, clock: FakeClock, probe: Probe
) -> None:
    inst = two_hosts(tmp_path)
    builder.store.upsert([stored("new/1")])
    mark(inst, GITHUB, repo="app", now=clock.now())
    tick(inst)
    assert builder.started == []

    clock.advance(MINUTE)
    probe.healthy = True
    tick(inst)

    assert builder.started == ["new/1"]
