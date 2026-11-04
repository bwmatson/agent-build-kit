"""One marker for each code host (spec: git-host-outage, each code host has one marker and one
authenticated check): what it records, the wait that grows along the park ladder and resets on a
pass, and the one probe a refresh makes for it.

The probe is a stand-in; the marker files are the state directory's own."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline import code_host, network_probe, pause
from tests.code_host_fixtures import (
    AZURE,
    AZURE_URL,
    GITHUB,
    GITHUB_URL,
    REFUSED,
    Probe,
    give_remote,
)
from tests.conftest import make_installation
from tests.fake_clock import FakeClock, install

MINUTE = 60


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return install(monkeypatch)


def test_a_marker_records_the_host_when_it_began_and_the_last_error(
    tmp_path: Path, clock: FakeClock
) -> None:
    pause.note_host_outage(tmp_path, GITHUB, repo="app", error=REFUSED, now=clock.now())

    marker = pause.host_outage(tmp_path, GITHUB)

    assert marker is not None
    assert (marker.host, marker.repo, marker.last_error) == (GITHUB, "app", REFUSED)
    assert marker.since == marker.last_checked == clock.now()
    assert marker.failed_probes == 0


def test_a_second_unit_refreshes_the_error_and_leaves_the_rest(
    tmp_path: Path, clock: FakeClock
) -> None:
    began = clock.now()
    pause.note_host_outage(tmp_path, GITHUB, repo="app", error="first", now=began)
    pause.record_host_probe(tmp_path, GITHUB, healthy=False, error="probe", now=began)
    clock.advance(30)

    pause.note_host_outage(tmp_path, GITHUB, repo="platform", error="second", now=clock.now())

    marker = pause.host_outage(tmp_path, GITHUB)
    assert marker is not None
    assert (marker.since, marker.failed_probes, marker.repo) == (began, 1, "app")
    assert marker.last_error == "second"


def test_each_host_has_a_marker_of_its_own(tmp_path: Path, clock: FakeClock) -> None:
    pause.note_host_outage(tmp_path, GITHUB, repo="app", error="a", now=clock.now())

    assert pause.host_outage(tmp_path, AZURE) is None
    pause.note_host_outage(tmp_path, AZURE, repo="platform", error="b", now=clock.now())

    assert {each.host for each in pause.host_outages(tmp_path)} == {GITHUB, AZURE}
    pause.record_host_probe(tmp_path, GITHUB, healthy=True, error="", now=clock.now())
    assert {each.host for each in pause.host_outages(tmp_path)} == {AZURE}


def test_the_wait_grows_along_the_park_ladder(tmp_path: Path, clock: FakeClock) -> None:
    pause.note_host_outage(tmp_path, GITHUB, repo="app", error=REFUSED, now=clock.now())
    waits = []
    for _ in range(7):
        marker = pause.host_outage(tmp_path, GITHUB)
        assert marker is not None
        waits.append(marker.wait() // timedelta(minutes=1))
        pause.record_host_probe(tmp_path, GITHUB, healthy=False, error=REFUSED, now=clock.now())

    assert waits == [1, 2, 5, 10, 30, 30, 30]


def test_a_new_outage_after_a_long_quiet_gap_starts_fresh_at_the_first_wait(
    tmp_path: Path, clock: FakeClock
) -> None:
    pause.note_host_outage(tmp_path, GITHUB, repo="app", error=REFUSED, now=clock.now())
    for _ in range(4):
        pause.record_host_probe(tmp_path, GITHUB, healthy=False, error=REFUSED, now=clock.now())
    pause.record_host_probe(tmp_path, GITHUB, healthy=True, error="", now=clock.now())
    clock.advance(31 * MINUTE)  # past the longest wait: a different outage

    pause.note_host_outage(tmp_path, GITHUB, repo="app", error="again", now=clock.now())

    again = pause.host_outage(tmp_path, GITHUB)
    assert again is not None
    assert (again.wait(), again.failed_probes, again.since) == (
        timedelta(minutes=1),
        0,
        clock.now(),
    )


def test_a_unit_parking_soon_after_a_pass_reopens_the_same_outage(
    tmp_path: Path, clock: FakeClock
) -> None:
    began = clock.now()
    pause.note_host_outage(tmp_path, GITHUB, repo="app", error=REFUSED, now=began)
    pause.record_host_probe(tmp_path, GITHUB, healthy=False, error=REFUSED, now=clock.now())
    clock.advance(2 * MINUTE)
    pause.record_host_probe(tmp_path, GITHUB, healthy=True, error="", now=clock.now())
    clock.advance(MINUTE)

    pause.note_host_outage(tmp_path, GITHUB, repo="app", error="pushed, refused", now=clock.now())

    marker = pause.host_outage(tmp_path, GITHUB)
    assert marker is not None
    assert marker.since == began, "the outage did not start again"
    assert (marker.failed_probes, marker.flaps) == (2, 1), "a re-park counts as a failure"
    assert marker.wait() == timedelta(minutes=5)


def test_a_read_that_passes_while_the_push_is_refused_reaches_the_limit_and_says_so(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ls-remote` passes (a read-only key), the units are released, push, are refused and park
    again, over and over."""
    inst = two_hosts(tmp_path)
    Probe(monkeypatch, healthy=True)
    pause.note_host_outage(inst.state_dir, GITHUB, repo="app", error=REFUSED, now=clock.now())
    waits = []
    for _ in range(8):
        marker = pause.host_outage(inst.state_dir, GITHUB)
        assert marker is not None
        waits.append(marker.wait() // timedelta(minutes=1))
        clock.advance(marker.wait().total_seconds())
        assert code_host.refresh(inst).cleared == (GITHUB,)
        clock.advance(MINUTE)  # the released unit pushes and is refused
        pause.note_host_outage(inst.state_dir, GITHUB, repo="app", error=REFUSED, now=clock.now())

    assert waits == sorted(waits) and waits[-1] == 30, waits
    [long] = code_host.long_outages(inst, clock.now())
    assert long.host == GITHUB
    assert "cleared" in code_host.outage_text(long, clock.now())


def test_a_pass_with_no_repark_still_clears_the_outage_for_good(
    tmp_path: Path, clock: FakeClock
) -> None:
    pause.note_host_outage(tmp_path, GITHUB, repo="app", error=REFUSED, now=clock.now())
    pause.record_host_probe(tmp_path, GITHUB, healthy=True, error="", now=clock.now())

    assert pause.host_outage(tmp_path, GITHUB) is None
    assert pause.host_outages(tmp_path) == []


def test_a_probe_is_due_only_when_the_wait_has_passed(tmp_path: Path, clock: FakeClock) -> None:
    pause.note_host_outage(tmp_path, GITHUB, repo="app", error=REFUSED, now=clock.now())
    marker = pause.host_outage(tmp_path, GITHUB)
    assert marker is not None

    assert not marker.probe_due(clock.now() + timedelta(seconds=MINUTE - 1))
    assert marker.probe_due(clock.now() + timedelta(seconds=MINUTE))


def test_a_passing_probe_clears_the_marker_and_says_when(tmp_path: Path, clock: FakeClock) -> None:
    pause.note_host_outage(tmp_path, GITHUB, repo="app", error=REFUSED, now=clock.now())
    clock.advance(90)

    pause.record_host_probe(tmp_path, GITHUB, healthy=True, error="", now=clock.now())

    assert pause.host_outage(tmp_path, GITHUB) is None
    assert pause.host_released_at(tmp_path, GITHUB) == clock.now()


# --- the one probe of a refresh ---------------------------------------------------------


def two_hosts(tmp_path: Path):
    inst = make_installation(tmp_path)
    give_remote(inst, "app", GITHUB_URL)
    give_remote(inst, "platform", AZURE_URL)
    return inst


def test_a_refresh_makes_one_probe_for_a_marker_whatever_asks_again(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = two_hosts(tmp_path)
    probe = Probe(monkeypatch)
    pause.note_host_outage(inst.state_dir, GITHUB, repo="app", error=REFUSED, now=clock.now())
    clock.advance(MINUTE)

    code_host.refresh(inst)
    code_host.refresh(inst)
    code_host.refresh(inst)

    assert probe.calls == [inst.checkouts["app"]]


def test_a_refresh_makes_one_probe_for_each_marker_from_its_own_repo(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = two_hosts(tmp_path)
    probe = Probe(monkeypatch)
    pause.note_host_outage(inst.state_dir, GITHUB, repo="app", error=REFUSED, now=clock.now())
    pause.note_host_outage(inst.state_dir, AZURE, repo="platform", error="401", now=clock.now())
    clock.advance(MINUTE)

    code_host.refresh(inst)

    assert sorted(probe.calls) == sorted([inst.checkouts["app"], inst.checkouts["platform"]])


def test_a_refresh_sooner_than_the_wait_makes_no_probe_and_each_failure_lengthens_it(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = two_hosts(tmp_path)
    probe = Probe(monkeypatch)
    pause.note_host_outage(inst.state_dir, GITHUB, repo="app", error=REFUSED, now=clock.now())

    for wait in (1, 2, 5, 10, 30, 30):
        before = len(probe.calls)
        clock.advance(wait * MINUTE - 1)
        code_host.refresh(inst)
        assert len(probe.calls) == before, f"probed a second early at a wait of {wait} minutes"
        clock.advance(1)
        code_host.refresh(inst)
        assert len(probe.calls) == before + 1, f"did not probe at a wait of {wait} minutes"

    marker = pause.host_outage(inst.state_dir, GITHUB)
    assert marker is not None and marker.failed_probes == 6


def test_a_passing_probe_clears_the_marker_and_reports_the_host(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = two_hosts(tmp_path)
    Probe(monkeypatch, healthy=True)
    pause.note_host_outage(inst.state_dir, GITHUB, repo="app", error=REFUSED, now=clock.now())
    clock.advance(MINUTE)

    result = code_host.refresh(inst)

    assert result.cleared == (GITHUB,)
    assert pause.host_outage(inst.state_dir, GITHUB) is None


def test_a_probe_that_breaks_counts_the_host_healthy(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = two_hosts(tmp_path)

    def broken(checkout: Path, **kwargs: object) -> network_probe.HostProbe:
        raise RuntimeError("a bug in the probe")

    monkeypatch.setattr(network_probe, "code_host_healthy", broken)
    pause.note_host_outage(inst.state_dir, GITHUB, repo="app", error=REFUSED, now=clock.now())
    clock.advance(MINUTE)

    code_host.refresh(inst)

    assert pause.host_outage(inst.state_dir, GITHUB) is None


def test_a_marker_whose_repo_is_gone_counts_the_host_healthy(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = two_hosts(tmp_path)
    probe = Probe(monkeypatch)
    pause.note_host_outage(inst.state_dir, GITHUB, repo="removed", error=REFUSED, now=clock.now())
    clock.advance(MINUTE)

    code_host.refresh(inst)

    assert probe.calls == []
    assert pause.host_outage(inst.state_dir, GITHUB) is None


def test_the_host_of_a_repo_is_that_of_its_origin_and_none_without_one(
    tmp_path: Path,
) -> None:
    inst = two_hosts(tmp_path)

    assert code_host.host_of(inst.checkouts["app"]) == GITHUB
    assert code_host.host_of(inst.checkouts["platform"]) == AZURE
    assert code_host.host_of(tmp_path / "no-such-checkout") is None
