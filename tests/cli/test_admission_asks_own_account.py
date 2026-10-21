"""A ready unit is admitted only when its own account's usage decision allows it (spec:
capacity-checks, admission asks the unit's own account).

`app` runs on the default account and `platform` on `personal`. The guard's decision is a stand-in
that answers per account and counts how often it was asked; a round is `run_round`, which returns
the units it would start, so nothing is prepared, branched or leased by these tests.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.checkpointer import unit_graphs_path
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.pause import is_paused
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.vocabulary import WaitReason
from agent_build_kit.pipeline.wait_log import recorded_waits
from agent_build_kit.pipeline.wiring import build_usage_gate
from tests.conftest import make_installation
from tests.factories import own_group
from tests.pipeline.test_cli_pipeline import stored

PERSONAL = "personal"


class Accounts:
    """The usage decision of each account (None is the default one), and how often each was
    asked."""

    def __init__(self) -> None:
        self.full: set[str | None] = set()
        self.asked: dict[str | None, int] = {}

    def decide(self, account: claude_account.Account | None) -> Decision:
        label = account.label if account else None
        self.asked[label] = self.asked.get(label, 0) + 1
        if label not in self.full:
            return Decision(may_start=True, reason="plenty")
        who = f"account {label}: " if label else ""
        return Decision(
            may_start=False,
            reason=f"{who}weekly usage at 93% (threshold 93%)",
            resume_at=spans.clock.now() + timedelta(hours=3),
        )

    def __call__(self, *, account: claude_account.Account | None = None, **_: object) -> Decision:
        return self.decide(account)


@pytest.fixture
def accounts(monkeypatch: pytest.MonkeyPatch) -> Accounts:
    answers = Accounts()
    monkeypatch.setattr(cli, "decide_start", answers)
    return answers


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("poll_all", "fetch_all", "plan_all"):
        monkeypatch.setattr(cli, name, lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    (tmp_path / "planning").mkdir()
    with closing(sqlite3.connect(unit_graphs_path(tmp_path / "planning"))) as conn:
        conn.execute("PRAGMA journal_mode=WAL")


def unit(uid: str, repo: str) -> StoredUnit:
    change = uid.partition("/")[0]
    return stored(uid, change=change, repo=repo, groups=own_group(uid, change))


def workspace(tmp_path: Path, units: list[StoredUnit]) -> tuple[Installation, UnitStore]:
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": ".", "worktree_root": str(tmp_path / "trees")},
        repos={
            "app": {"path": str(tmp_path / "app"), "slug": "example/app"},
            "platform": {
                "path": str(tmp_path / "platform"),
                "slug": "example/platform",
                "account": PERSONAL,
            },
        },
        runtimes={"claude_code": {"accounts": {PERSONAL: {"config_dir": str(tmp_path / "p")}}}},
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert(units)
    return inst, store


def round_of(inst: Installation, store: UnitStore) -> list[str]:
    ready = cli.run_round(inst, store, building=(), only=frozenset(), submit=True)
    return [each.id for each in ready]


def waits(inst: Installation) -> dict[str, WaitReason]:
    found = recorded_waits(inst.state_dir / cli.DECISIONS_NAME)
    return {uid: wait.reason for uid, (wait, _since) in found.items()}


def test_a_round_starts_the_open_accounts_units_and_none_of_the_full_ones(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = workspace(
        tmp_path, [unit("one/1", "app"), unit("two/1", "platform"), unit("three/1", "platform")]
    )
    accounts.full = {PERSONAL}

    assert round_of(inst, store) == ["one/1"]

    assert waits(inst) == {"two/1": WaitReason.USAGE_PAUSE, "three/1": WaitReason.USAGE_PAUSE}
    leases = Leases(lease_dir(inst.state_dir))
    for uid in ("two/1", "three/1"):
        assert not store.get(uid).branch
        assert leases.holder(uid) is None
    assert not (tmp_path / "trees").exists()
    assert is_paused(inst.state_dir / "paused.json") is None


def test_the_full_accounts_units_start_in_order_when_its_reading_clears(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = workspace(
        tmp_path, [unit("one/1", "app"), unit("two/1", "platform"), unit("three/1", "platform")]
    )
    accounts.full = {PERSONAL}
    assert round_of(inst, store) == ["one/1"]

    accounts.full = set()

    later = round_of(inst, store)
    assert [uid for uid in later if uid != "one/1"] == ["two/1", "three/1"]


def test_a_unit_already_started_is_not_held_back_while_a_fresh_one_of_its_account_is(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = workspace(
        tmp_path, [unit("one/1", "app"), unit("two/1", "platform"), unit("three/1", "platform")]
    )
    store.set_state("two/1", RUNNING, branch="spec/two/1")
    accounts.full = {PERSONAL}

    started = round_of(inst, store)

    assert "three/1" not in started
    assert "two/1" in started


def test_the_decision_for_an_account_is_made_once_a_round_however_many_units_are_ready(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = workspace(
        tmp_path,
        [unit("one/1", "app"), *(unit(f"unit{n}/1", "platform") for n in range(3))],
    )
    accounts.full = {PERSONAL}

    round_of(inst, store)

    assert accounts.asked == {None: 1, PERSONAL: 1}


@pytest.mark.parametrize(("repo", "full"), [("platform", PERSONAL), ("app", None)])
def test_admission_is_allowed_exactly_when_the_first_agent_steps_gate_allows(
    tmp_path: Path, accounts: Accounts, repo: str, full: str | None
) -> None:
    """One account is full and the other has room, so the round goes on: the unit on the full
    account is refused by its gate and so must not be admitted, the other's must be."""
    other = "platform" if repo == "app" else "app"
    inst, store = workspace(tmp_path, [unit("mine/1", repo), unit("other/1", other)])
    accounts.full = {full}
    allowed = {}
    for name in (repo, other):
        account = claude_account.for_repo(inst.config, name)
        may_start, _resume_at = build_usage_gate(start=lambda each=account: accounts.decide(each))
        allowed[name] = may_start()[0]

    admitted = round_of(inst, store)

    assert ("mine/1" in admitted) == allowed[repo]
    assert ("other/1" in admitted) == allowed[other]
