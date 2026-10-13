"""The calibrated allowances are kept with their inputs in `usage-allowances.json`.

The file sits beside the guard's cache file. One that is missing, unreadable or of another
shape means no calibration, never an error (spec: usage-pause)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.config import ClaudeLimitsConfig
from agent_build_kit.pipeline.usage_allowances import (
    ALLOWANCES_NAME,
    Calibrated,
    read_allowances,
    refresh_allowances,
    write_allowances,
)
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from tests.usage_allowance_records import keep, per_unit

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
LIMITS = ClaudeLimitsConfig()
WINDOW_KEYS = {"quantile_pct_per_unit", "quantile", "pairs_used", "pairs_available", "computed_at"}


def calibrated(raw: float | None, pairs: int) -> Calibrated:
    return Calibrated(
        quantile_pct_per_unit=raw,
        quantile=0.9,
        pairs_used=pairs,
        pairs_available=pairs,
        computed_at=NOW,
    )


def test_a_refresh_keeps_each_window_with_its_quantile_pairs_and_time(tmp_path: Path) -> None:
    calls, ledger = per_unit("weekly", [1] * 9)
    keep(tmp_path, calls, ledger)

    refresh_allowances(tmp_path, limits=LIMITS, now=NOW)

    kept = json.loads((tmp_path / ALLOWANCES_NAME).read_text())
    assert set(kept["weekly"]) == WINDOW_KEYS
    assert kept["weekly"]["quantile_pct_per_unit"] == 1
    assert (kept["weekly"]["pairs_used"], kept["weekly"]["pairs_available"]) == (9, 9)
    assert kept["weekly"]["quantile"] == 0.9
    assert datetime.fromisoformat(kept["weekly"]["computed_at"]) == NOW


def test_what_was_written_is_what_is_read(tmp_path: Path) -> None:
    path = tmp_path / ALLOWANCES_NAME
    found = {"session": calibrated(9, 24), "weekly": calibrated(None, 3)}

    write_allowances(path, found)

    assert read_allowances(path) == found
    assert [p.name for p in tmp_path.iterdir()] == [ALLOWANCES_NAME]


def test_a_missing_file_means_no_calibration(tmp_path: Path) -> None:
    assert read_allowances(tmp_path / ALLOWANCES_NAME) == {}


@pytest.mark.parametrize(
    "text", ["{not json", "[1, 2]", '{"weekly": "x"}', '{"weekly": {"pairs_used": "many"}}', ""]
)
def test_a_file_that_is_unreadable_or_of_another_shape_means_no_calibration(
    tmp_path: Path, text: str
) -> None:
    path = tmp_path / ALLOWANCES_NAME
    path.write_text(text)

    assert read_allowances(path) == {}


def test_a_directory_where_the_file_should_be_means_no_calibration(tmp_path: Path) -> None:
    (tmp_path / ALLOWANCES_NAME).mkdir()

    assert read_allowances(tmp_path / ALLOWANCES_NAME) == {}


def test_a_ledger_that_cannot_be_read_leaves_the_kept_result_as_it_was(tmp_path: Path) -> None:
    path = tmp_path / ALLOWANCES_NAME
    write_allowances(path, {"weekly": calibrated(1, 24)})
    (tmp_path / LEDGER_NAME).mkdir()

    refresh_allowances(tmp_path, limits=LIMITS, now=NOW)

    assert read_allowances(path) == {"weekly": calibrated(1, 24)}
