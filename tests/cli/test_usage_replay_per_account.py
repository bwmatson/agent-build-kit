"""`abk usage replay --account <label>` replays the readings of one account (spec: claude-accounts,
usage and slots are per account).

The record and the ledger carry an account key, so a record that alternates between two accounts
is replayed for the one asked, and for the default account without the flag.
"""

from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from tests.conftest import make_installation
from tests.usage_allowance_records import START, STEP, gaps, keep

ACCOUNT = "/accounts/kit"


def replayed(tmp_path: Path, capsys: pytest.CaptureFixture[str], *flags: str) -> list[str]:
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": "."},
        runtimes={"claude_code": {"accounts": {"kit": {"config_dir": ACCOUNT}}}},
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    default, default_spent = gaps("weekly", [(10, 12, 1), (20, 22, 1)])
    second, second_spent = gaps("weekly", [(50, 55, 1), (60, 65, 1)], start=START + 2 * STEP)
    calls = [c.model_copy(update={"account": None}) for c in default]
    calls += [c.model_copy(update={"account": ACCOUNT}) for c in second]
    ledger = [r.model_copy(update={"account": None}) for r in default_spent]
    ledger += [
        r.model_copy(update={"unit": "k" + r.unit, "account": ACCOUNT}) for r in second_spent
    ]
    keep(inst.state_dir, calls, ledger)

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
