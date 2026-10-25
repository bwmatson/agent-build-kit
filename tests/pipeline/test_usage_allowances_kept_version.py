"""The kept file is `{"version": 2, "windows": {...}}`: the previous reader reads it as no
calibration, this reader reads the previous shape as the flat calibration it was, and neither
fails on a file it cannot use (spec: usage-pause)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_build_kit.claude_account import Account
from agent_build_kit.config import ClaudeLimitsConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_allowances import (
    ALLOWANCES_NAME,
    allowances_path,
    read_allowances,
    refresh_allowances,
    write_allowances,
)
from tests.usage_allowance_records import calibrated, keep, per_unit
from tests.usage_cost_records import Gap, cost_gaps

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
LIMITS = ClaudeLimitsConfig()
PREVIOUS_KEYS = {
    "quantile_pct_per_unit",
    "quantile",
    "pairs_used",
    "pairs_available",
    "computed_at",
}
WINDOW_KEYS = PREVIOUS_KEYS | {
    "basis",
    "reason",
    "points_per_usd",
    "intercept_per_hour",
    "safety_scale",
    "cost_pairs_held",
    "cost_pairs_judged",
    "false_allows_cost",
    "false_allows_flat",
}


class PreviousCalibrated(Frozen):
    """What the previous version kept for one window."""

    quantile_pct_per_unit: float | None
    quantile: float
    pairs_used: int
    pairs_available: int
    computed_at: datetime


def previous_read_allowances(path: Path) -> dict[str, PreviousCalibrated]:
    """The previous version's reader, as it was."""
    try:
        body = json.loads(path.read_text())
        if not isinstance(body, dict):
            return {}
        return {name: PreviousCalibrated.model_validate(each) for name, each in body.items()}
    except (OSError, ValueError, ValidationError):
        return {}


def test_what_is_kept_is_the_version_and_the_windows_with_the_fields_of_the_spec(
    tmp_path: Path,
) -> None:
    calls, ledger = per_unit("weekly", [1] * 9)
    keep(tmp_path, calls, ledger)

    refresh_allowances(tmp_path, limits=LIMITS, now=NOW)

    kept = json.loads((tmp_path / ALLOWANCES_NAME).read_text())
    assert set(kept) == {"version", "windows"}
    assert kept["version"] == 2
    assert set(kept["windows"]) == {"session", "weekly"}
    assert set(kept["windows"]["weekly"]) == WINDOW_KEYS
    assert kept["windows"]["weekly"]["quantile_pct_per_unit"] == 1
    assert (kept["windows"]["weekly"]["pairs_used"], kept["windows"]["weekly"]["basis"]) == (
        9,
        "units",
    )


def test_a_write_is_whole_and_leaves_nothing_beside_it(tmp_path: Path) -> None:
    path = tmp_path / ALLOWANCES_NAME
    found = {"session": calibrated(9, 24), "weekly": calibrated(None, 3)}

    write_allowances(path, found)

    assert json.loads(path.read_text())["version"] == 2
    assert read_allowances(path) == found
    assert [p.name for p in tmp_path.iterdir()] == [ALLOWANCES_NAME]


def test_the_previous_reader_reads_the_new_file_as_no_calibration(tmp_path: Path) -> None:
    path = tmp_path / ALLOWANCES_NAME

    write_allowances(path, {"session": calibrated(9, 24), "weekly": calibrated(1, 24)})

    assert json.loads(path.read_text())["version"] == 2
    assert previous_read_allowances(path) == {}


def test_a_file_of_the_previous_shape_is_the_flat_calibration_it_was(tmp_path: Path) -> None:
    path = tmp_path / ALLOWANCES_NAME
    path.write_text(
        json.dumps(
            {
                "session": {
                    "quantile_pct_per_unit": 9.0,
                    "quantile": 0.9,
                    "pairs_used": 24,
                    "pairs_available": 24,
                    "computed_at": NOW.isoformat(),
                }
            }
        )
    )

    found = read_allowances(path)

    assert found == {
        "session": calibrated(9.0, 24, at=NOW).model_copy(
            update={"basis": "units", "reason": "previous file"}
        )
    }


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="empty"),
        pytest.param("{not json", id="not-json"),
        pytest.param('{"version": 2, "windows": {"session": {"quantile', id="truncated"),
        pytest.param("[1, 2]", id="not-an-object"),
        pytest.param('{"version": 3, "windows": {}}', id="unknown-version"),
        pytest.param('{"version": 2, "windows": []}', id="windows-not-an-object"),
        pytest.param('{"version": 2, "windows": {"session": "x"}}', id="window-not-an-object"),
    ],
)
def test_a_file_that_cannot_be_used_is_no_calibration_and_the_next_tick_rewrites_it(
    tmp_path: Path, text: str
) -> None:
    path = tmp_path / ALLOWANCES_NAME
    path.write_text(text)
    calls, ledger = per_unit("weekly", [1] * 9)
    keep(tmp_path, calls, ledger)

    assert read_allowances(path) == {}
    refresh_allowances(tmp_path, limits=LIMITS, now=NOW)

    assert json.loads(path.read_text())["version"] == 2
    assert read_allowances(path)["weekly"].quantile_pct_per_unit == 1


def test_a_version_this_reader_does_not_know_is_no_calibration(tmp_path: Path) -> None:
    path = tmp_path / ALLOWANCES_NAME
    write_allowances(path, {"weekly": calibrated(1, 24)})
    body = json.loads(path.read_text())

    path.write_text(json.dumps({**body, "version": 3}))

    assert read_allowances(path) == {}


def test_calibration_off_keeps_a_version_two_file_with_no_windows(tmp_path: Path) -> None:
    calls, ledger = per_unit("weekly", [1] * 9)
    keep(tmp_path, calls, ledger)

    refresh_allowances(
        tmp_path, limits=ClaudeLimitsConfig(calibrate_usage_allowances=False), now=NOW
    )

    assert json.loads((tmp_path / ALLOWANCES_NAME).read_text()) == {"version": 2, "windows": {}}


def test_each_account_is_refreshed_from_its_own_readings_and_ledger_rows(tmp_path: Path) -> None:
    kit = Account(label="kit", config_dir=tmp_path / "kit-account")
    key = str(kit.config_dir)
    costs = (1.0, 2.0, 3.0, 4.0)

    def gaps(per_dollar: int) -> list[Gap]:
        return [
            Gap(gain=per_dollar * round(costs[i % 4]), cost=costs[i % 4], hours=1.0 + (i % 3) / 2)
            for i in range(12)
        ]

    keep(tmp_path, *cost_gaps("weekly", gaps(3)))
    keep(tmp_path, *cost_gaps("weekly", gaps(5), account=key), account=kit)

    refresh_allowances(tmp_path, limits=LIMITS, now=NOW, accounts=[Account(), kit])

    default_kept = json.loads(allowances_path(tmp_path, Account.default()).read_text())
    kit_kept = json.loads(allowances_path(tmp_path, kit).read_text())
    assert default_kept["version"] == kit_kept["version"] == 2
    assert default_kept["windows"]["weekly"]["points_per_usd"] == pytest.approx(3.00, abs=1e-9)
    assert kit_kept["windows"]["weekly"]["points_per_usd"] == pytest.approx(5.00, abs=1e-9)
