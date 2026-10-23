"""The guard records a unit's forecast once and every step it admits, under the ledger's lock, and
a record that cannot be written never refuses a start (spec: usage-accounting)."""

from datetime import UTC, datetime
from pathlib import Path

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
    record_admission(path, row, forecast(row.unit), enabled=enabled, say=(said or []).append)


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


def test_with_the_forecast_off_nothing_is_written(tmp_path: Path) -> None:
    path = tmp_path / FORECASTS_NAME

    admit(path, step(), enabled=False)

    assert not path.exists()


def test_the_guard_records_the_step_it_admits(host: Host) -> None:
    paused(host, session=10.0)

    decision = decide_start(unit="feature/1", step="review")

    assert decision.may_start
    steps = read_record(host.cache.parent / FORECASTS_NAME).steps
    assert [(s.unit, s.node) for s in steps] == [("feature/1", "review")]


def test_the_guard_records_the_same_ask_once(host: Host) -> None:
    paused(host, session=10.0)

    decide_start(unit="feature/1", step="review")
    decide_start(unit="feature/1", step="review")

    assert len(read_record(host.cache.parent / FORECASTS_NAME).steps) == 1


def test_the_guard_writes_nothing_with_the_forecast_off(host: Host) -> None:
    paused(host, session=10.0, usage_forecast=False)

    decision = decide_start(unit="feature/1", step="review")

    assert decision.may_start
    assert not (host.cache.parent / FORECASTS_NAME).exists()
