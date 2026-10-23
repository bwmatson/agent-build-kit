"""What each ask of the guard is forecast as: the round's own ask the lowest tier among the units
that can start, a track's or the planner's one call at its mean, and a unit's later gate the step
asked and not its whole path (spec: usage-pause)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.pause import is_paused
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.usage_forecast_record import (
    FORECASTS_NAME,
    ForecastRow,
    StepRow,
    WindowForecast,
    record_admission,
)
from agent_build_kit.pipeline.usage_guard import decide_start
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, append_record
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.cli.vanished_fakes import keep_changes_of_unstarted_units
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.usage_forecast_fixtures import call, spec_history
from tests.usage_forecast_gate import EXACT, ask, held, keep_points, lay, lay_calls
from tests.usage_host import Host, payload

FULL = ReviewTier.FULL
LIMITS = {
    "session": {"usage_pause_pct": 80},
    "weekly": {"usage_pause_pct": 80},
    "usage_climb_floor": 2.0,
    **EXACT,
}
MINUTE = timedelta(minutes=1)


@pytest.fixture
def inst(tmp_path: Path, host: Host) -> Installation:
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": "."},
        runtimes={"claude_code": {"limits": LIMITS}},
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    host.keep_in(inst.state_dir)
    return inst


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    keep_changes_of_unstarted_units(monkeypatch)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: False)


def round_of(inst: Installation, store: UnitStore) -> list[str]:
    ready = cli.run_round(inst, store, building=set(), started=set(), only=frozenset(), submit=True)
    return [unit.id for unit in ready]


def test_the_round_s_ask_forecasts_the_lowest_tier_among_the_units_that_can_start(
    inst: Installation, host: Host
) -> None:
    """A round with only a `full` unit to start is refused at 67%, and one that also has an
    `auto` unit is not: a unit that cannot fit is refused at its own gate."""
    keep_points(host)
    host.answers = [payload(session=67.0), payload(session=67.0)]
    lay(host, spec_history())
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit("feature/1", change="feature", review_tier="full")])

    assert round_of(inst, store) == []
    assert is_paused(inst.state_dir / "paused.json") is not None

    store.upsert([stored_unit("other/1", change="other", review_tier="auto")])

    assert "other/1" in round_of(inst, store)


def test_a_track_s_ask_is_forecast_as_one_call_at_its_mean(host: Host) -> None:
    """A health track's call costs $4.00, 10 points: 67 plus 10 plus 5 is not under 80."""
    held(host, session=67.0)
    lay_calls(host, "track_health", 4.0)

    refusal = ask(None, "track:health", step="track_health")

    assert not refusal.may_start
    assert "forecast" in refusal.reason
    assert "track_health" in refusal.reason


def test_a_track_whose_call_fits_is_allowed(host: Host) -> None:
    held(host, session=67.0)
    lay_calls(host, "track_health", 4.0)
    lay_calls(host, "track_improve", 1.0)

    assert not ask(None, "track:health", step="track_health").may_start
    assert ask(None, "track:improve", step="track_improve").may_start


def test_the_planner_s_ask_is_forecast_as_one_call_at_its_mean(host: Host) -> None:
    held(host, session=67.0)
    lay_calls(host, "plan", 4.0)

    refusal = decide_start(step="plan")

    assert not refusal.may_start
    assert "forecast" in refusal.reason
    assert "plan" in refusal.reason


def earlier(host: Host, unit: str) -> None:
    """`unit` of tier `full` was admitted earlier: a forecast row and a step row for its first."""
    path = host.cache.parent / FORECASTS_NAME
    now = datetime.now(UTC)
    first = StepRow(unit=unit, node="implement", round=0, at=now - 60 * MINUTE)
    row = ForecastRow(
        unit=unit,
        tier=FULL,
        band="all",
        at=now - 30 * MINUTE,
        session=WindowForecast(usd=3.42, points=8.55),
        weekly=WindowForecast(usd=3.42, points=8.55),
        parts={"review": 1.57},
        prior=False,
    )
    record_admission(path, first, row, enabled=True, say=pytest.fail)
    # Its first step has ended, so the unit is not running.
    append_record(
        host.cache.parent / LEDGER_NAME,
        call(unit, "implement", 0, 0.6, at=(now - 58 * MINUTE).isoformat()),
    )


def test_a_later_gate_is_judged_on_the_step_asked_and_not_the_whole_path(host: Host) -> None:
    """At 73% the whole path of 8.6 points would be refused, the review round 2 at $0.50 and
    1.25 points fits, and a review round 1 at $1.00 and 2.5 points does not."""
    held(host, session=73.0)
    lay(host, spec_history())
    earlier(host, "full/1")
    earlier(host, "full/2")

    fits = ask(FULL, "full/1", step="review", step_round=2)
    over = ask(FULL, "full/2", step="review", step_round=1)

    assert fits.may_start
    assert not over.may_start
    assert "forecast" in over.reason
