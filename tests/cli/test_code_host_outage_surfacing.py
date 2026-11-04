"""A long code-host outage is shown and never fails a unit (spec: git-host-outage): within
`global_limits.code_host_outage_minutes` only the normal wait shows; past it `abk status`, the tick
log and `abk doctor` name the host, how long it has been down and the last error, and doctor hints
at the SSH key or agent. Units stay parked throughout."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import doctor
from agent_build_kit.pipeline import pause
from agent_build_kit.pipeline.units import PLANNED
from tests.code_host_fixtures import GITHUB, GITHUB_URL, Probe, give_remote, mark, park
from tests.conftest import run_status
from tests.fake_clock import FakeClock, install
from tests.tick_pass import Builder, install_builder, isolate, tick, warm_unit_graphs, workspace

pytestmark = pytest.mark.usefixtures("scripted_engine")

MINUTE = 60
ERROR = "git@github.com: Permission denied (publickey)."


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


def down_for(tmp_path: Path, builder: Builder, clock: FakeClock, minutes: int, **overrides):
    """A host whose first probe failed and whose outage began `minutes` ago, with a parked unit."""
    inst = workspace(tmp_path, **overrides)
    give_remote(inst, "app", GITHUB_URL)
    park(builder.store, "one/1")
    mark(inst, GITHUB, repo="app", now=clock.now(), error=ERROR)
    pause.record_host_probe(inst.state_dir, GITHUB, healthy=False, error=ERROR, now=clock.now())
    clock.advance(minutes * MINUTE)
    return inst


def lines_of(inst, monkeypatch, capsys) -> list[str]:
    return run_status(inst, monkeypatch, capsys)


def test_status_past_the_limit_names_the_host_the_time_down_and_the_last_error(
    tmp_path: Path,
    builder: Builder,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = down_for(tmp_path, builder, clock, 75)

    shown = "\n".join(lines_of(inst, monkeypatch, capsys))

    line = next(line for line in shown.splitlines() if "75 minutes" in line)
    assert GITHUB in line and "Permission denied (publickey)" in line
    assert builder.store.get("one/1").state == PLANNED, "the limit failed a unit"


def test_status_within_the_limit_shows_only_the_wait(
    tmp_path: Path,
    builder: Builder,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = down_for(tmp_path, builder, clock, 59)

    lines = lines_of(inst, monkeypatch, capsys)

    waiting = [line for line in lines if "one/1" in line and "waiting for the code host" in line]
    assert waiting and f"({GITHUB})" in waiting[0]
    assert not [line for line in lines if "minutes" in line and "Permission denied" in line]
    assert not [line for line in lines if "unreachable" in line]


def test_the_limit_is_the_configured_one(
    tmp_path: Path,
    builder: Builder,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = down_for(tmp_path, builder, clock, 11, limits={"code_host_outage_minutes": 10})

    shown = "\n".join(lines_of(inst, monkeypatch, capsys))

    assert "11 minutes" in shown


def test_a_marker_with_no_failed_probe_is_not_yet_a_long_outage(
    tmp_path: Path,
    builder: Builder,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = workspace(tmp_path)
    give_remote(inst, "app", GITHUB_URL)
    mark(inst, GITHUB, repo="app", now=clock.now(), error=ERROR)
    clock.advance(120 * MINUTE)

    assert not [line for line in lines_of(inst, monkeypatch, capsys) if "120 minutes" in line]


def test_the_tick_log_says_it_once_for_a_refresh_and_fails_no_unit(
    tmp_path: Path,
    builder: Builder,
    clock: FakeClock,
    probe: Probe,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = down_for(tmp_path, builder, clock, 75)
    capsys.readouterr()

    assert tick(inst) == 0

    said = [line for line in capsys.readouterr().out.splitlines() if "75 minutes" in line]
    assert len(said) == 1, said
    assert GITHUB in said[0] and "Permission denied (publickey)" in said[0]
    assert builder.started == []
    assert builder.store.get("one/1").state == PLANNED


def test_the_tick_log_within_the_limit_has_no_outage_line(
    tmp_path: Path,
    builder: Builder,
    clock: FakeClock,
    probe: Probe,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst = down_for(tmp_path, builder, clock, 30)
    capsys.readouterr()

    tick(inst)

    assert not [
        line
        for line in capsys.readouterr().out.splitlines()
        if "minutes" in line and GITHUB in line and "unreachable" in line
    ]


# --- abk doctor ------------------------------------------------------------------------------


def test_doctor_past_the_limit_hints_at_the_key_and_agent(
    tmp_path: Path, builder: Builder, clock: FakeClock
) -> None:
    inst = down_for(tmp_path, builder, clock, 75)

    [found] = doctor._code_host_outage(inst)

    assert found.name == doctor.CODE_HOST_OUTAGE
    assert found.status == "warn"
    assert GITHUB in found.detail and "75 minutes" in found.detail
    assert "Permission denied (publickey)" in found.detail
    assert "SSH key" in found.fix and "agent" in found.fix


def test_doctor_within_the_limit_says_nothing(
    tmp_path: Path, builder: Builder, clock: FakeClock
) -> None:
    assert doctor._code_host_outage(down_for(tmp_path, builder, clock, 59)) == []


def test_doctor_with_no_marker_says_nothing(tmp_path: Path) -> None:
    assert doctor._code_host_outage(workspace(tmp_path)) == []
