"""A pass readmits a unit parked for the network or the model service only once its backoff
has elapsed, on the table a unit parked for the code host reads: 1, 2, 5, 10 and 30 minutes
by consecutive parking, 30 thereafter. Until then it is skipped and the log says how long
remains; then it resumes at the step it stopped on."""

from __future__ import annotations

import argparse

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.cli.test_tick_scheduling import (  # noqa: F401
    Builder,
    builder,
    isolated,
    stored,
    tick,
    warm_unit_graphs,
    workspace,
)
from tests.fake_clock import FakeClock, install

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT = "feature/1"
MINUTE = 60
BACKOFF_MINUTES = [1, 2, 5, 10, 30, 30, 30]
CAUSES = ["network_unavailable", "service_unavailable"]


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


def park(store: UnitStore, cause: str, *, attempts: int) -> None:
    """The unit as a build leaves it after being parked `attempts` times in a row, now."""
    store.upsert([stored(UNIT)])
    for _ in range(attempts):
        store.record_step(UNIT, "implement")
        store.set_state(UNIT, PLANNED, note="API Error: EAI_AGAIN", cause=Cause(cause))


@pytest.mark.parametrize("cause", CAUSES)
@pytest.mark.parametrize("attempts", range(1, len(BACKOFF_MINUTES) + 1))
def test_the_pass_skips_a_parked_unit_until_its_backoff_has_elapsed(
    tmp_path,
    builder: Builder,  # noqa: F811
    clock: FakeClock,
    attempts: int,
    cause: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    park(builder.store, cause, attempts=attempts)
    inst = workspace(tmp_path)

    clock.advance(BACKOFF_MINUTES[attempts - 1] * MINUTE - 1)
    tick(inst)
    assert builder.started == [], "readmitted a second early"
    waiting = [line for line in capsys.readouterr().out.splitlines() if UNIT in line]
    assert any("remain" in line for line in waiting), "the log does not say how long remains"

    clock.advance(2)
    tick(inst)
    assert builder.started == [UNIT]


@pytest.mark.parametrize("cause", CAUSES)
def test_a_parked_unit_is_readmitted_once_its_backoff_has_elapsed(
    tmp_path,
    builder: Builder,  # noqa: F811
    clock: FakeClock,
    cause: str,
) -> None:
    park(builder.store, cause, attempts=1)
    clock.advance(MINUTE + 1)

    tick(workspace(tmp_path))

    assert builder.started == [UNIT]
    assert builder.store.get(UNIT).state != PLANNED or builder.store.get(UNIT).cause != cause


@pytest.mark.parametrize(
    ("cause", "line"),
    [
        ("network_unavailable", "waiting for the network"),
        ("service_unavailable", "waiting for the model service"),
    ],
)
def test_status_says_which_of_the_two_the_unit_waits_for(
    tmp_path,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cause: str,
    line: str,
) -> None:
    inst = workspace(tmp_path)
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    store = UnitStore(tmp_path / "units.json")
    park(store, cause, attempts=1)

    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    lines = capsys.readouterr().out.splitlines()
    waiting = next(entry for entry in lines if UNIT in entry and "waiting for the" in entry)
    assert f"{line}: {UNIT} (app) at implement, 60s remain — API Error: EAI_AGAIN" in waiting
    assert "code host" not in waiting
