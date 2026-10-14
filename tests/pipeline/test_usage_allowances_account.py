"""The calibration of the allowances restarts when the account changes (spec: usage-account).

Only the readings after the last line of a different account are paired, so points gained on
one account are never paired with a reading of another; a record of one account (or of none)
is calibrated whole.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.config import ClaudeLimitsConfig
from agent_build_kit.pipeline.usage_allowances import (
    ALLOWANCES_NAME,
    Calibrated,
    read_allowances,
    refresh_allowances,
)
from agent_build_kit.pipeline.usage_calls import UsageCall
from agent_build_kit.pipeline.usage_ledger import UsageRecord
from agent_build_kit.settings import settings
from tests.usage_allowance_records import START, STEP, keep, per_unit, segments

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
LIMITS = ClaudeLimitsConfig()
ENOUGH = LIMITS.usage_allowance_min_pairs + 1


def of(account: str | None, calls: list[UsageCall]) -> list[UsageCall]:
    return [each.model_copy(update={"account": account}) for each in calls]


def refreshed(state_dir: Path) -> Calibrated:
    refresh_allowances(state_dir, limits=LIMITS, now=NOW)
    return read_allowances(state_dir / ALLOWANCES_NAME)["weekly"]


def use(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> str:
    directory = tmp_path / name
    monkeypatch.setattr(settings, "claude_home", directory)
    return str(directory)


def later(count: int, gain: int, after: int) -> tuple[list[UsageCall], list[UsageRecord]]:
    """`count` segments of `gain` points a unit, laid out after `after` earlier ones."""
    return segments("weekly", [(gain * 2, 2)] * count, start=START + after * STEP)


def test_the_pairs_of_the_old_account_are_not_paired_with_the_new_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = use(monkeypatch, tmp_path, "b")
    old, old_spent = per_unit("weekly", [5] * 10)
    new, new_spent = later(ENOUGH, 1, 10)
    keep(tmp_path / "one", of(b, old + new), old_spent + new_spent)
    one = refreshed(tmp_path / "one")
    keep(tmp_path / "two", of(str(tmp_path / "a"), old) + of(b, new), old_spent + new_spent)

    found = refreshed(tmp_path / "two")

    assert one.pairs_available == 10 + ENOUGH
    assert found.pairs_available == ENOUGH
    assert found.quantile_pct_per_unit == 1


def test_too_few_pairs_after_the_change_keep_the_configured_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    b = use(monkeypatch, tmp_path, "b")
    old, old_spent = per_unit("weekly", [5] * 10)
    new, new_spent = later(1, 1, 10)
    keep(tmp_path / "state", of(str(tmp_path / "a"), old) + of(b, new), old_spent + new_spent)

    found = refreshed(tmp_path / "state")

    assert found.pairs_available == 1
    assert found.quantile_pct_per_unit is None


def test_a_return_to_the_first_account_counts_only_the_readings_after_the_last_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = use(monkeypatch, tmp_path, "a")
    first, first_spent = per_unit("weekly", [5] * 10)
    middle, middle_spent = later(10, 3, 10)
    last, last_spent = later(ENOUGH, 1, 20)
    keep(
        tmp_path / "state",
        of(a, first) + of(str(tmp_path / "b"), middle) + of(a, last),
        first_spent + middle_spent + last_spent,
    )

    found = refreshed(tmp_path / "state")

    assert found.pairs_available == ENOUGH
    assert found.quantile_pct_per_unit == 1
