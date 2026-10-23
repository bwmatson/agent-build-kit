"""A plan call that is due and a track whose timer fires before a window resets reserve their
mean cost for that window, released when their ledger row is written (spec: usage-pause)."""

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.pipeline.usage_forecast_reservations import (
    TimerReading,
    TrackTimer,
    read_timers,
    reserve,
)
from agent_build_kit.pipeline.usage_ledger import UsageRecord
from tests.usage_forecast_fixtures import call

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)
SESSION_RESET = NOW + 2 * HOUR
WEEKLY_RESET = NOW + timedelta(days=3)


def timers(**tracks: TrackTimer) -> TimerReading:
    return TimerReading(read=True, tracks=tracks)


def fires_in(delta: timedelta, *, last: datetime | None = None) -> TrackTimer:
    return TrackTimer(next_elapse=NOW + delta, last_trigger=last)


def mean_costs(**usd: float) -> list[UsageRecord]:
    """Two rows of each node at `usd` dollars."""
    return [
        call(f"{node}-{n}", node, 0, cost, at=(NOW - 10 * HOUR).isoformat())
        for node, cost in usd.items()
        for n in range(2)
    ]


def reserved(
    records: list[UsageRecord],
    read: TimerReading,
    *,
    resets_at: datetime = SESSION_RESET,
    plan_due: bool = False,
    proposing: tuple[str, ...] = (),
):
    return reserve(
        records,
        read,
        plan_due=plan_due,
        proposing=proposing,
        resets_at=resets_at,
        now=NOW,
        points_per_usd=2.5,
    )


def test_a_track_firing_before_the_session_reset_reserves_its_mean_cost() -> None:
    found = reserved(mean_costs(track_health=2.0), timers(track_health=fires_in(HOUR)))

    [track] = found.items
    assert (track.name, track.usd, track.points) == ("track_health", 2.0, 5.0)
    assert found.timers_read


def test_the_same_track_reserves_for_the_weekly_window_when_it_fires_after_the_session_one() -> (
    None
):
    health = timers(track_health=fires_in(5 * HOUR))
    records = mean_costs(track_health=2.0)

    session = reserved(records, health)
    weekly = reserved(records, health, resets_at=WEEKLY_RESET)

    assert session.items == ()
    assert [r.name for r in weekly.items] == ["track_health"]


def test_a_track_that_fires_after_the_window_resets_reserves_nothing_for_it() -> None:
    found = reserved(
        mean_costs(track_health=2.0),
        timers(track_health=fires_in(timedelta(days=5))),
        resets_at=WEEKLY_RESET,
    )

    assert found.items == ()


def test_a_plan_call_due_reserves_the_plan_cells_mean() -> None:
    found = reserved(mean_costs(plan=0.2), timers(), plan_due=True)

    [plan] = found.items
    assert (plan.name, plan.usd, plan.points) == ("plan", 0.2, 0.5)


def test_a_plan_call_not_due_reserves_nothing() -> None:
    assert reserved(mean_costs(plan=0.2), timers()).items == ()


def test_track_propose_is_added_with_a_track_that_proposes() -> None:
    found = reserved(
        mean_costs(track_improve=1.0, track_propose=0.5),
        timers(track_improve=fires_in(HOUR)),
        proposing=("track_improve",),
    )

    assert {r.name: r.usd for r in found.items} == {"track_improve": 1.0, "track_propose": 0.5}


def test_a_track_is_released_once_its_ledger_row_is_written() -> None:
    fired = NOW - 5 * timedelta(minutes=1)
    health = timers(track_health=TrackTimer(next_elapse=NOW + 20 * HOUR, last_trigger=fired))
    records = mean_costs(track_health=2.0)
    written = call("", "track_health", 0, 2.0, at=(NOW - timedelta(minutes=1)).isoformat())

    before = reserved(records, health)
    after = reserved([*records, written], health)

    assert [r.name for r in before.items] == ["track_health"]
    assert after.items == ()


def test_unreadable_timers_reserve_no_track_and_say_so() -> None:
    found = reserved(
        mean_costs(track_health=2.0, plan=0.2),
        TimerReading(read=False, tracks={}),
        plan_due=True,
    )

    assert [r.name for r in found.items] == ["plan"]
    assert not found.timers_read


class Systemctl:
    """`systemctl --user show` as it answers: one `Property=value` per line, in its own
    time format, for the units it has."""

    def __init__(self, units: dict[str, str] | None = None, *, code: int = 0) -> None:
        self.units = units or {}
        self.code = code
        self.asked: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.asked.append(argv)
        out = next((text for name, text in self.units.items() if name in argv), "")
        return subprocess.CompletedProcess(argv, self.code, stdout=out, stderr="")


def shown(next_elapse: str, last: str = "n/a") -> str:
    return f"NextElapseUSecRealtime={next_elapse}\nLastTriggerUSec={last}\n"


def test_the_timers_are_read_from_systemctl_show(tmp_path: Path) -> None:
    name = f"abk-{tmp_path.name}-track-health.timer"
    run = Systemctl({name: shown("Thu 2026-01-01 13:00:00 UTC", "Wed 2025-12-31 13:00:00 UTC")})

    read = read_timers(tmp_path, run=run)

    assert read.read
    assert read.tracks["track_health"] == TrackTimer(
        next_elapse=datetime(2026, 1, 1, 13, tzinfo=UTC),
        last_trigger=datetime(2025, 12, 31, 13, tzinfo=UTC),
    )
    assert all(argv[:3] == ["systemctl", "--user", "show"] for argv in run.asked)


def test_a_timer_that_never_fired_has_no_last_trigger(tmp_path: Path) -> None:
    name = f"abk-{tmp_path.name}-track-health.timer"

    read = read_timers(tmp_path, run=Systemctl({name: shown("Thu 2026-01-01 13:00:00 UTC")}))

    assert read.tracks["track_health"].last_trigger is None


def test_systemctl_failing_leaves_the_timers_unread(tmp_path: Path) -> None:
    read = read_timers(tmp_path, run=Systemctl(code=1))

    assert not read.read
    assert read.tracks == {}


def test_no_systemctl_leaves_the_timers_unread(tmp_path: Path) -> None:
    def missing(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        raise FileNotFoundError("systemctl")

    read = read_timers(tmp_path, run=missing)

    assert not read.read
