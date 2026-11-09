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
from agent_build_kit.pipeline.units import PLANNED
from tests.code_host_fixtures import (
    AZURE_URL,
    GITHUB,
    GITHUB_URL,
    Probe,
    give_remote,
    mark,
    park,
)
from tests.fake_clock import FakeClock, install
from tests.tick_pass import (
    Builder,
    install_builder,
    isolate,
    stored,
    tick,
    warm_unit_graphs,
    workspace,
)

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


# --- a focused pause on new starts ---------------------------------------------------------------


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
