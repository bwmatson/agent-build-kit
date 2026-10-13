"""An estimate adds the calibrated allowance the tick kept, else the configured one.

The kept result is a file beside the guard's cache; an estimate reads it and never
recomputes from the record (spec: usage-pause). Only the endpoint and the home directory
are faked (`tests/usage_host.py`)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline import usage_allowances
from agent_build_kit.pipeline.usage_allowances import (
    ALLOWANCES_NAME,
    Calibrated,
    write_allowances,
)
from agent_build_kit.pipeline.usage_guard import decide_start
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, append_record
from tests.usage_allowance_records import calibrated, spend
from tests.usage_host import Host, configure, payload, refused

MINUTE = timedelta(minutes=1)


def paused_on_a_reading(host: Host, *, units: int, **limits: object) -> None:
    """The weekly at 70% in a reading 89 minutes old, the endpoint refusing, and `units`
    units that have spent since."""
    configure(session={"usage_pause_pct": 92}, weekly={"usage_pause_pct": 80}, **limits)
    host.keep_reading(89 * MINUTE, payload(session=0.0, weekly=70.0))
    refused(host, cooling=3 * MINUTE)
    for index in range(units):
        record = spend(f"add-marker/{index}", datetime.now(UTC) - 10 * MINUTE)
        append_record(host.cache.parent / LEDGER_NAME, record)


def keep_allowances(host: Host, **found: Calibrated) -> None:
    write_allowances(host.cache.parent / ALLOWANCES_NAME, found)


def test_the_kept_weekly_allowance_is_the_one_added_for_each_unit(host: Host) -> None:
    paused_on_a_reading(host, units=3)
    keep_allowances(host, weekly=calibrated(1))

    decision = decide_start()

    assert "weekly ~73% estimated (70% read + 3% spent)" in decision.reason
    assert decision.may_start
    assert host.asked == 0


def test_a_window_the_kept_result_leaves_out_has_its_configured_allowance(host: Host) -> None:
    paused_on_a_reading(host, units=3)
    keep_allowances(host, weekly=calibrated(1))

    decision = decide_start()

    assert "session ~30% estimated (0% read + 30% spent)" in decision.reason


def test_with_nothing_kept_the_configured_allowance_is_added(host: Host) -> None:
    paused_on_a_reading(host, units=3)
    keep_allowances(host, weekly=calibrated(1))
    assert "weekly ~73%" in decide_start().reason

    (host.cache.parent / ALLOWANCES_NAME).unlink()

    assert "weekly ~76% estimated (70% read + 6% spent)" in decide_start().reason


def test_with_calibration_off_every_window_has_its_configured_allowance(host: Host) -> None:
    paused_on_a_reading(host, units=3, calibrate_usage_allowances=False)
    keep_allowances(host, weekly=calibrated(1), session=calibrated(9))

    decision = decide_start()

    assert "weekly ~76% estimated (70% read + 6% spent)" in decision.reason
    assert "session ~30% estimated (0% read + 30% spent)" in decision.reason


def test_a_kept_file_that_cannot_be_read_means_the_configured_allowances(host: Host) -> None:
    paused_on_a_reading(host, units=3)
    keep_allowances(host, weekly=calibrated(1))
    assert "weekly ~73%" in decide_start().reason

    (host.cache.parent / ALLOWANCES_NAME).write_text("{not json")

    assert "weekly ~76% estimated (70% read + 6% spent)" in decide_start().reason


def test_deciding_two_units_calibrates_nothing_from_the_record(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    paused_on_a_reading(host, units=1)
    keep_allowances(host, weekly=calibrated(1))
    computed: list[int] = []
    real = usage_allowances.calibrated_allowances

    def counting(*args: object, **kwargs: object) -> object:
        computed.append(1)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(usage_allowances, "calibrated_allowances", counting)

    first = decide_start(unit="add-marker/7")
    second = decide_start(unit="add-marker/8")

    assert first.may_start and second.may_start
    assert computed == []
    assert Path(host.cache.parent / ALLOWANCES_NAME).exists()
