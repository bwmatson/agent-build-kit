"""One read API for what the outside world says: a value and its age, and the round that fills it.

A step reads a snapshot and asks for a refresh when it is old; the round, which is the one
collector, refreshes what was asked for or is over its limit and clears the requests
(spec: snapshots). The collectors are plain callables, so no host or endpoint is involved.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.forges.base import Check, CheckStatus
from agent_build_kit.pipeline import snapshots
from agent_build_kit.pipeline.pr_poller import HOLD_LABEL, PrState, snapshot, state_path
from agent_build_kit.pipeline.snapshots import Pauses, Request
from agent_build_kit.pipeline.usage_guard import UsageReading
from tests import fake_clock
from tests.fake_clock import FakeClock
from tests.usage_host import usage_reading

MINUTE = timedelta(minutes=1)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return fake_clock.install(monkeypatch)


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "runs"


def reading(session: int = 20) -> UsageReading:
    return usage_reading(session, taken=fake_clock.START)


def record_pull(state_dir: Path, repo: str, pull: PullRequest) -> None:
    PrState.save(state_path(state_dir, repo), {str(pull.number): snapshot(pull)}, repo)


class Collected:
    """A collector that returns a fixed value and notes the keys it was asked for."""

    def __init__(self, value: object) -> None:
        self.value = value
        self.keys: list[str | None] = []

    def __call__(self, key: str | None) -> object:
        self.keys.append(key)
        return self.value


# --- a snapshot returns its value and its age ------------------------------------------


def test_a_pull_request_snapshot_returns_its_merge_state_checks_and_labels(
    clock: FakeClock, state_dir: Path
) -> None:
    pull = PullRequest(
        number=7,
        head="spec/feature/1",
        base="main",
        state="open",
        labels=(HOLD_LABEL,),
        checks=(Check(name="build", status=CheckStatus.FAILED),),
        mergeable=False,
    )
    record_pull(state_dir, "app", pull)

    found = snapshots.pr(state_dir, "app", 7)

    assert found.value is not None
    assert found.value.state == "open"
    assert found.value.mergeable is False
    assert found.value.checks == {"build": "failed"}
    assert HOLD_LABEL in found.value.labels


def test_a_snapshots_age_is_the_time_since_it_was_collected(
    clock: FakeClock, state_dir: Path
) -> None:
    record_pull(
        state_dir, "app", PullRequest(number=7, head="spec/feature/1", base="main", state="open")
    )
    clock.advance(90)

    found = snapshots.pr(state_dir, "app", 7)

    assert found.collected_at == fake_clock.START
    assert found.age == timedelta(seconds=90)


def test_a_pull_request_nobody_collected_has_no_value_and_no_age(
    clock: FakeClock, state_dir: Path
) -> None:
    record_pull(
        state_dir, "app", PullRequest(number=7, head="spec/feature/1", base="main", state="open")
    )

    assert snapshots.pr(state_dir, "app", 8).value is None
    assert snapshots.pr(state_dir, "app", 8).age is None
    assert snapshots.pr(state_dir, "platform", 7).value is None


def test_a_usage_snapshot_returns_the_reading_the_round_collected_and_its_age(
    clock: FakeClock, state_dir: Path
) -> None:
    snapshots.request_refresh(state_dir, snapshots.USAGE, "acct")
    snapshots.run_round(state_dir, {snapshots.USAGE: Collected(reading(31))}, {})
    clock.advance(120)

    found = snapshots.usage(state_dir, "acct")

    assert found.value == reading(31)
    assert found.age == 2 * MINUTE
    assert snapshots.usage(state_dir, "other").value is None


def test_the_pause_snapshot_returns_the_markers_the_round_collected_and_their_age(
    clock: FakeClock, state_dir: Path
) -> None:
    paused = Pauses(resume_at={"feature/1": fake_clock.START + timedelta(hours=1)})
    snapshots.request_refresh(state_dir, snapshots.PAUSES)
    snapshots.run_round(state_dir, {snapshots.PAUSES: Collected(paused)}, {})
    clock.advance(30)

    found = snapshots.pauses(state_dir)

    assert found.value == paused
    assert found.age == timedelta(seconds=30)


# --- a refresh request is one per kind and key -----------------------------------------


def test_a_refresh_request_is_recorded_with_its_kind_and_key(state_dir: Path) -> None:
    snapshots.request_refresh(state_dir, snapshots.USAGE, "acct")

    assert snapshots.requested(state_dir) == [Request(kind="usage", key="acct")]
    assert json.loads((state_dir / "refresh-requests.json").read_text())


def test_asking_again_for_the_same_kind_and_key_records_nothing_more(state_dir: Path) -> None:
    for _ in range(3):
        snapshots.request_refresh(state_dir, snapshots.USAGE, "acct")

    assert snapshots.requested(state_dir) == [Request(kind="usage", key="acct")]


def test_a_request_per_key_and_per_kind_is_kept_apart(state_dir: Path) -> None:
    snapshots.request_refresh(state_dir, snapshots.USAGE, "one")
    snapshots.request_refresh(state_dir, snapshots.USAGE, "two")
    snapshots.request_refresh(state_dir, snapshots.PR, "one")
    snapshots.request_refresh(state_dir, snapshots.PAUSES)

    assert sorted(snapshots.requested(state_dir), key=lambda each: (each.kind, each.key or "")) == [
        Request(kind="pauses", key=None),
        Request(kind="pr", key="one"),
        Request(kind="usage", key="one"),
        Request(kind="usage", key="two"),
    ]


def test_a_request_touches_the_wake_file(state_dir: Path) -> None:
    snapshots.request_refresh(state_dir, snapshots.PR, "app")

    assert (state_dir / "wake").exists()


# --- the round refreshes what was asked for or is over its limit ------------------------


def test_the_round_refreshes_what_was_requested_and_clears_the_requests(
    clock: FakeClock, state_dir: Path
) -> None:
    usage = Collected(reading())
    snapshots.request_refresh(state_dir, snapshots.USAGE, "acct")

    snapshots.run_round(state_dir, {snapshots.USAGE: usage}, {snapshots.USAGE: 10 * MINUTE})

    assert usage.keys == ["acct"]
    assert snapshots.requested(state_dir) == []


def test_the_round_leaves_a_snapshot_inside_its_limit_alone(
    clock: FakeClock, state_dir: Path
) -> None:
    usage = Collected(reading())
    snapshots.request_refresh(state_dir, snapshots.USAGE, "acct")
    snapshots.run_round(state_dir, {snapshots.USAGE: usage}, {snapshots.USAGE: 10 * MINUTE})
    clock.advance(5 * 60)

    snapshots.run_round(state_dir, {snapshots.USAGE: usage}, {snapshots.USAGE: 10 * MINUTE})

    assert usage.keys == ["acct"]


def test_the_round_refreshes_a_snapshot_over_its_limit_without_a_request(
    clock: FakeClock, state_dir: Path
) -> None:
    usage = Collected(reading())
    snapshots.request_refresh(state_dir, snapshots.USAGE, "acct")
    snapshots.run_round(state_dir, {snapshots.USAGE: usage}, {snapshots.USAGE: 10 * MINUTE})
    clock.advance(11 * 60)

    snapshots.run_round(state_dir, {snapshots.USAGE: usage}, {snapshots.USAGE: 10 * MINUTE})

    assert usage.keys == ["acct", "acct"]
    assert snapshots.usage(state_dir, "acct").age == timedelta(0)


def test_the_round_refreshes_a_pull_request_repo_over_its_limit_by_its_name(
    clock: FakeClock, state_dir: Path
) -> None:
    record_pull(
        state_dir, "app", PullRequest(number=7, head="spec/feature/1", base="main", state="open")
    )
    prs = Collected(None)
    clock.advance(6 * 60)

    snapshots.run_round(state_dir, {snapshots.PR: prs}, {snapshots.PR: 5 * MINUTE})

    assert prs.keys == ["app"]


def test_the_round_refreshes_only_the_kinds_that_have_a_collector(
    clock: FakeClock, state_dir: Path
) -> None:
    snapshots.request_refresh(state_dir, snapshots.USAGE, "acct")
    snapshots.request_refresh(state_dir, snapshots.PAUSES)
    pauses = Collected(Pauses())

    snapshots.run_round(state_dir, {snapshots.PAUSES: pauses}, {})

    assert pauses.keys == [None]
    assert snapshots.requested(state_dir) == [Request(kind="usage", key="acct")]


def test_a_stored_value_that_no_longer_validates_reads_as_not_collected(
    clock: FakeClock, state_dir: Path
) -> None:
    at = fake_clock.START.isoformat()
    bad = {"value": {"nonsense": True}, "collected_at": at}
    state_dir.mkdir()
    (state_dir / snapshots.STORE).write_text(
        json.dumps({snapshots.USAGE: {"": bad}, snapshots.PAUSES: {"": bad}})
    )

    assert snapshots.usage(state_dir, None) == snapshots.Snapshot()
    assert snapshots.pauses(state_dir) == snapshots.Snapshot()


def test_a_collector_that_raises_is_told_and_its_request_stays_while_the_rest_go_on(
    clock: FakeClock, state_dir: Path
) -> None:
    def failing(key: str | None) -> object:
        raise OSError("endpoint down")

    pauses = Collected(Pauses())
    told: list[str] = []
    snapshots.request_refresh(state_dir, snapshots.USAGE, "acct")
    snapshots.request_refresh(state_dir, snapshots.PAUSES)

    snapshots.run_round(
        state_dir, {snapshots.USAGE: failing, snapshots.PAUSES: pauses}, {}, say=told.append
    )

    assert pauses.keys == [None]
    assert len(told) == 1 and "usage acct" in told[0] and "endpoint down" in told[0]
    assert snapshots.requested(state_dir) == [Request(kind="usage", key="acct")]
