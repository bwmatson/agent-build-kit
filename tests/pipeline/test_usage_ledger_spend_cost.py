"""The ledger reader of spend by cost, which keeps rows with no unit (spec: usage-pause, the
estimate counts cost over every row of the account)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_build_kit.claude_account import Account
from agent_build_kit.pipeline.usage_allowances import of_account
from agent_build_kit.pipeline.usage_ledger import read_ledger, spend_costs, spend_times
from tests.pipeline.test_usage_ledger import line, write


def at(minute: int) -> str:
    return f"2026-01-01T10:{minute:02d}:00+00:00"


def when(minute: int) -> datetime:
    return datetime.fromisoformat(at(minute))


def test_every_row_is_returned_once_with_its_cost_and_the_unit_pairs_still_skip_a_blank_unit(
    tmp_path: Path,
) -> None:
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(unit="", node="plan", session_id=None, cost_usd=0.4, at=at(1)),
        line(unit="", node="login_refresh", session_id=None, cost_usd=None, at=at(2)),
        line(node="review", round=1, session_id="r1", cost_usd=0.1, at=at(3)),
        line(node="review", round=2, session_id="r2", cost_usd=0.2, at=at(4)),
        line(node="review", round=3, session_id="r3", cost_usd=0.3, at=at(5)),
        line(node="implement", session_id="s1", cost_usd=0.5, at=at(6)),
        line(node="implement", session_id="s1", resumed=True, cost_usd=0.25, at=at(7)),
        line(node="verify", session_id="s2", cost_usd=0.6, at=at(8)),
        line(node="verify", session_id="s2", cost_usd=0.9, at=at(9)),
        line(node="restack", session_id=None, cost_usd=0.7, at="not a time"),
        line(node="fix", round=1, session_id="f1", cost_usd=-1.0, at=at(10)),
        line(node="fix", round=2, session_id="f2", cost_usd="lots", at=at(11)),
    )
    records = read_ledger(ledger)

    rows = spend_costs(records)

    assert [(r.at, r.unit, r.node, round(r.cost_usd, 6)) for r in rows] == [
        (when(1), "", "plan", 0.4),
        (when(2), "", "login_refresh", 0.0),
        (when(3), "add-marker/1", "review", 0.1),
        (when(4), "add-marker/1", "review", 0.2),
        (when(5), "add-marker/1", "review", 0.3),
        (when(7), "add-marker/1", "implement", 0.75),
        (when(9), "add-marker/1", "verify", 0.9),
        (when(10), "add-marker/1", "fix", 0.0),
        (when(11), "add-marker/1", "fix", 0.0),
    ]
    pairs = spend_times(records)
    assert [unit for _, unit in pairs] == ["add-marker/1"] * 7
    assert [t for t, _ in pairs] == [when(m) for m in (3, 4, 5, 7, 9, 10, 11)]


def test_a_labelled_account_gets_its_own_rows_and_a_row_with_no_key_is_the_default_accounts(
    tmp_path: Path,
) -> None:
    kit = Account(label="kit", config_dir=tmp_path / "kit-account")
    key = str(tmp_path / "kit-account")
    ledger = write(
        tmp_path / "usage-ledger.jsonl",
        line(unit="", node="plan", session_id=None, cost_usd=0.1, at=at(1), account=key),
        line(unit="", node="plan", session_id=None, cost_usd=0.2, at=at(2), account="/other"),
        line(unit="", node="plan", session_id=None, cost_usd=0.4, at=at(3)),
    )
    records = read_ledger(ledger)

    kits = spend_costs(of_account([], records, kit)[1])
    default = spend_costs(of_account([], records, Account())[1])

    assert [r.cost_usd for r in kits] == [0.1]
    assert [r.cost_usd for r in default] == [0.4]
