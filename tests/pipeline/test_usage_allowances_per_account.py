"""Each account's allowances are calibrated from its own readings and its own spend (spec:
claude-accounts, usage and slots are per account).

A record that alternates between two accounts is not cut at each change: an account pairs the
readings it took and the units that ran on it, whatever the other account was doing between.
"""

from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.claude_account import Account
from agent_build_kit.config import ClaudeLimitsConfig
from agent_build_kit.pipeline.usage_allowances import calibrated_allowances
from agent_build_kit.pipeline.usage_calls import UsageCall
from agent_build_kit.pipeline.usage_ledger import UsageRecord
from tests.usage_allowance_records import START, STEP, segments

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
LIMITS = ClaudeLimitsConfig()
ENOUGH = LIMITS.usage_allowance_min_pairs + 1


def alternating(kit: Account) -> tuple[list[UsageCall], list[UsageRecord]]:
    """ENOUGH segments of one point a unit on the default account and as many of four on `kit`,
    each of one account laid between two of the other."""
    calls: list[UsageCall] = []
    ledger: list[UsageRecord] = []
    key = str(kit.config_dir)
    for index in range(ENOUGH):
        for offset, (account, gain) in enumerate(((None, 1), (key, 4))):
            start = START + (2 * index + offset) * STEP
            made, spent = segments("weekly", [(gain * 2, 2)], start=start)
            calls += [each.model_copy(update={"account": account}) for each in made]
            ledger += [
                each.model_copy(
                    update={"account": account, "unit": f"{each.unit}-{index}-{offset}"}
                )
                for each in spent
            ]
    return calls, ledger


def test_each_account_pairs_only_its_own_readings(tmp_path: Path) -> None:
    kit = Account(label="kit", config_dir=tmp_path / "kit-account")
    calls, ledger = alternating(kit)

    first = calibrated_allowances(calls, ledger, limits=LIMITS, now=NOW, account=Account())
    second = calibrated_allowances(calls, ledger, limits=LIMITS, now=NOW, account=kit)

    assert (first["weekly"].pairs_available, first["weekly"].quantile_pct_per_unit) == (ENOUGH, 1)
    assert (second["weekly"].pairs_available, second["weekly"].quantile_pct_per_unit) == (
        ENOUGH,
        4,
    )
