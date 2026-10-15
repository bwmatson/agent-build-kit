"""`abk usage replay` pairs only the readings after the last change of account, as the
calibration does (spec: usage-account): the gap from the last reading of one account to the
first of the next is not a usable gap."""

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.settings import settings
from tests.conftest import make_installation
from tests.usage_allowance_records import START, gaps, keep, spend

HOUR = timedelta(hours=1)


def test_a_gap_across_a_change_of_account_is_not_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path / "planning", planning={"state_dir": "."}, runtimes={"claude_code": {}}
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "claude_home", tmp_path / "b")
    calls, ledger = gaps("weekly", [(10, 12, 1), (20, 22, 1)])
    accounts = ["/other", "/other", str(tmp_path / "b"), str(tmp_path / "b")]
    calls = [c.model_copy(update={"account": a}) for c, a in zip(calls, accounts, strict=True)]
    # A unit spent between the last reading of the other account and the first of this one.
    ledger.append(spend("across", START + 3 * HOUR))
    keep(inst.state_dir, calls, ledger)

    args = build_parser().parse_args(["usage", "replay"])
    assert args.func(args, inst) == 0

    shown = [each for each in capsys.readouterr().out.splitlines() if each.startswith("weekly at=")]
    assert len(shown) == 1
    assert "before=20" in shown[0]
