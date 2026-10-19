"""`abk usage replay --account <label>` replays the readings of one account (spec: claude-accounts,
usage and slots are per account).

Each account's readings are in the file the guard writes them to, and the ledger carries an account
key, so the account asked is replayed from its own record and the units that ran on it, and the
default account without the flag. A default-account unit that ran inside the other account's gap is
not that account's spend.
"""

from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.cli import build_parser
from tests.conftest import make_installation
from tests.usage_allowance_records import GAP, START, STEP, gaps, keep, spend

ACCOUNT = "/accounts/kit"


def replayed(tmp_path: Path, capsys: pytest.CaptureFixture[str], *flags: str) -> list[str]:
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": "."},
        runtimes={"claude_code": {"accounts": {"kit": {"config_dir": ACCOUNT}}}},
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    kit = claude_account.resolve(inst, "kit")
    default, default_spent = gaps("weekly", [(10, 12, 1), (20, 22, 1)])
    second_start = START + 2 * STEP
    second, second_spent = gaps("weekly", [(50, 55, 1), (60, 65, 1)], start=second_start)
    # A default-account unit that ran inside the first gap of the other account.
    stray = spend("stray", second_start + GAP / 4)
    keep(inst.state_dir, default, [*default_spent, stray])
    keep(
        inst.state_dir,
        [c.model_copy(update={"account": ACCOUNT}) for c in second],
        [r.model_copy(update={"unit": "k" + r.unit, "account": ACCOUNT}) for r in second_spent],
        account=kit,
    )

    args = build_parser().parse_args(["usage", "replay", *flags])
    assert args.func(args, inst) == 0

    return [each for each in capsys.readouterr().out.splitlines() if each.startswith("weekly at=")]


def test_the_flag_replays_that_accounts_gaps_and_without_it_the_default_accounts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    second = replayed(tmp_path / "second", capsys, "--account", "kit")
    default = replayed(tmp_path / "default", capsys)

    assert [("before=50" in each, "before=60" in each) for each in second] == [
        (True, False),
        (False, True),
    ]
    assert [("before=10" in each, "before=20" in each) for each in default] == [
        (True, False),
        (False, True),
    ]


def test_a_default_accounts_unit_in_the_other_accounts_gap_is_not_its_spend(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    second = replayed(tmp_path, capsys, "--account", "kit")

    assert all("units=1" in each for each in second)
