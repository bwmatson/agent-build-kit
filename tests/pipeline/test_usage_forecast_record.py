"""The guard records a unit's forecast once and every step it admits, under the ledger's lock, and
a record that cannot be written never refuses a start (spec: usage-accounting)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.usage_forecast_record import (
    FORECASTS_NAME,
    ForecastRow,
    StepRow,
    WindowForecast,
    read_record,
    record_admission,
)
from agent_build_kit.pipeline.usage_guard import decide_start
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.usage_cost_estimate import paused
from tests.usage_forecast_fixtures import spec_history
from tests.usage_forecast_gate import ask, lay, live
from tests.usage_host import Host

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)


def step(node: str = "review", round: int = 1, unit: str = "feature/1") -> StepRow:
    return StepRow(unit=unit, node=node, round=round, at=NOW)


def forecast(unit: str = "feature/1") -> ForecastRow:
    return ForecastRow(
        unit=unit,
        tier=ReviewTier.FULL,
        band="all",
        at=NOW,
        session=WindowForecast(usd=3.42, points=8.55),
        weekly=WindowForecast(usd=3.42, points=1.2),
        parts={"review/review": 1.57},
        prior=False,
    )


def admit(path: Path, row: StepRow, said: list[str] | None = None, *, enabled: bool = True) -> None:
    record_admission(
        path,
        row,
        forecast(row.unit),
        enabled=enabled,
        say=(said if said is not None else []).append,
    )


def test_the_first_step_of_a_unit_appends_a_forecast_row_and_a_step_row(tmp_path: Path) -> None:
    path = tmp_path / FORECASTS_NAME

    admit(path, step())

    record = read_record(path)
    assert record.forecasts == (forecast(),)
    assert record.steps == (step(),)
    assert path.with_name(f"{FORECASTS_NAME}.lock").exists()


def test_a_later_step_appends_only_a_step_row(tmp_path: Path) -> None:
    path = tmp_path / FORECASTS_NAME
    admit(path, step())

    admit(path, step("rework", 0))

    record = read_record(path)
    assert len(record.forecasts) == 1
    assert [(s.node, s.round) for s in record.steps] == [("review", 1), ("rework", 0)]


def test_the_same_ask_twice_appends_one_step_row(tmp_path: Path) -> None:
    path = tmp_path / FORECASTS_NAME

    admit(path, step())
    admit(path, step())

    record = read_record(path)
    assert len(record.forecasts) == 1
    assert len(record.steps) == 1


def test_a_record_that_cannot_be_written_says_so_and_raises_nothing(tmp_path: Path) -> None:
    blocker = tmp_path / "state"
    blocker.write_text("a file where the directory should be")
    said: list[str] = []

    admit(blocker / FORECASTS_NAME, step(), said)

    assert said


def test_a_half_written_last_line_is_skipped_and_the_others_are_read(tmp_path: Path) -> None:
    path = tmp_path / FORECASTS_NAME
    admit(path, step())
    with path.open("a") as record:
        record.write('{"kind": "step", "unit": "feature/1", "node": "rev')

    read = read_record(path)

    assert read.forecasts == (forecast(),)
    assert read.steps == (step(),)


def test_a_row_appended_after_a_cut_off_line_is_read(tmp_path: Path) -> None:
    path = tmp_path / FORECASTS_NAME
    admit(path, step())
    with path.open("a") as record:
        record.write('{"kind": "step", "unit": "feature/1", "node": "rev')

    admit(path, step(unit="feature/2"))

    read = read_record(path)
    assert read.forecasts == (forecast(), forecast("feature/2"))
    assert read.steps == (step(), step(unit="feature/2"))


def test_with_the_forecast_off_nothing_is_written(tmp_path: Path) -> None:
    path = tmp_path / FORECASTS_NAME

    admit(path, step(), enabled=False)

    assert not path.exists()


def test_the_guard_records_the_step_it_admits(host: Host) -> None:
    paused(host, session=10.0)

    decision = decide_start(unit="feature/1", step="review", step_round=2)

    assert decision.may_start
    steps = read_record(host.cache.parent / FORECASTS_NAME).steps
    assert [(s.unit, s.node, s.round) for s in steps] == [("feature/1", "review", 2)]


def test_the_guard_records_no_step_without_its_round(host: Host) -> None:
    paused(host, session=10.0)

    decide_start(unit="feature/1", step="review")

    assert not (host.cache.parent / FORECASTS_NAME).exists()


def test_the_guard_records_the_same_ask_once(host: Host) -> None:
    paused(host, session=10.0)

    decide_start(unit="feature/1", step="review", step_round=2)
    decide_start(unit="feature/1", step="review", step_round=2)

    assert len(read_record(host.cache.parent / FORECASTS_NAME).steps) == 1


def test_the_guard_writes_nothing_with_the_forecast_off(host: Host) -> None:
    paused(host, session=10.0, usage_forecast=False)

    decision = decide_start(unit="feature/1", step="review", step_round=2)

    assert decision.may_start
    assert not (host.cache.parent / FORECASTS_NAME).exists()


def test_the_guard_records_the_forecast_of_a_units_first_step_once(host: Host) -> None:
    live(host, session=10.0)
    lay(host, spec_history())

    first = ask(ReviewTier.AUTO, "auto/1", step="review", step_round=1)
    later = ask(ReviewTier.AUTO, "auto/1", step="review", step_round=2)

    assert first.may_start
    assert later.may_start
    record = read_record(host.cache.parent / FORECASTS_NAME)
    [row] = record.forecasts
    assert (row.unit, row.tier, row.band, row.prior) == ("auto/1", ReviewTier.AUTO, "all", False)
    assert row.session.usd == pytest.approx(2.55, abs=0.01)
    assert row.session.points == pytest.approx(6.4, abs=0.05)
    assert row.weekly.usd == row.session.usd
    assert sum(row.parts.values()) == pytest.approx(row.session.usd or 0.0)
    assert "review/review/1" in row.parts
    assert [(s.node, s.round) for s in record.steps] == [("review", 1), ("review", 2)]


def test_a_unit_with_no_history_is_recorded_on_the_prior(host: Host) -> None:
    live(host, session=10.0)

    ask(ReviewTier.FULL, "full/1", step="review", step_round=1)

    [row] = read_record(host.cache.parent / FORECASTS_NAME).forecasts
    assert row.prior
    assert row.session.usd is None
    assert row.parts == {}


def test_a_call_outside_a_units_graph_has_no_forecast_row(host: Host) -> None:
    live(host, session=10.0)

    decide_start(unit="track:health", step="track_health", step_round=0)

    assert read_record(host.cache.parent / FORECASTS_NAME).forecasts == ()
