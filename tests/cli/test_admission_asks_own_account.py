"""A ready unit is admitted only when its own account's usage decision allows it (spec:
capacity-checks, admission asks the unit's own account).

`app` runs on the default account and `platform` on `personal`. The guard's decision is a stand-in
that answers per account and counts how often it was asked; a round is `run_round`, which returns
the units it would start.
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
from agent_build_kit.pipeline import spans, wiring
from agent_build_kit.pipeline.pause import is_paused
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.vocabulary import WaitReason
from agent_build_kit.pipeline.wait_log import Wait, recorded_waits
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
    # One source for admission and for the gate of an agent step (`build_usage_gate`).
    monkeypatch.setattr(cli, "decide_start", answers)
    monkeypatch.setattr(wiring, "decide_start", answers)
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


def workspace(
    tmp_path: Path, units: list[StoredUnit], *, one_account: bool = False
) -> tuple[Installation, UnitStore]:
    named = {} if one_account else {"account": PERSONAL}
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": ".", "worktree_root": str(tmp_path / "trees")},
        repos={
            "app": {"path": str(tmp_path / "app"), "slug": "example/app"},
            "platform": {"path": str(tmp_path / "platform"), "slug": "example/platform", **named},
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


def waits(inst: Installation) -> dict[str, Wait]:
    found = recorded_waits(inst.state_dir / cli.DECISIONS_NAME)
    return {uid: wait for uid, (wait, _since) in found.items()}


def test_a_round_starts_the_open_accounts_units_and_none_of_the_full_ones(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = workspace(
        tmp_path, [unit("one/1", "app"), unit("two/1", "platform"), unit("three/1", "platform")]
    )
    accounts.full = {PERSONAL}

    assert round_of(inst, store) == ["one/1"]

    found = waits(inst)
    assert set(found) == {"two/1", "three/1"}
    for wait in found.values():
        assert wait.reason is WaitReason.USAGE_PAUSE
        assert f"account {PERSONAL}" in wait.detail
    assert is_paused(inst.state_dir / "paused.json") is None


def test_a_round_with_only_the_full_accounts_units_is_paused_and_the_pause_names_it(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = workspace(tmp_path, [unit("two/1", "platform"), unit("three/1", "platform")])
    accounts.full = {PERSONAL}

    assert round_of(inst, store) == []

    paused = is_paused(inst.state_dir / "paused.json")
    assert paused is not None
    assert f"account {PERSONAL}" in paused.reason


def test_an_installation_with_one_account_starts_its_units_while_the_account_has_room(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = workspace(
        tmp_path, [unit("one/1", "app"), unit("two/1", "platform")], one_account=True
    )

    assert round_of(inst, store) == ["one/1", "two/1"]
    assert not waits(inst)


def test_an_installation_with_one_account_pauses_when_the_account_is_full(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = workspace(
        tmp_path, [unit("one/1", "app"), unit("two/1", "platform")], one_account=True
    )
    accounts.full = {None}

    assert round_of(inst, store) == []

    assert is_paused(inst.state_dir / "paused.json") is not None


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


@pytest.mark.parametrize("branched", [False, True])
@pytest.mark.parametrize("full", [set(), {None}, {PERSONAL}, {None, PERSONAL}], ids=str)
@pytest.mark.parametrize("repo", ["app", "platform"])
def test_admission_is_allowed_exactly_when_the_first_agent_steps_gate_allows(
    tmp_path: Path, accounts: Accounts, repo: str, full: set[str | None], branched: bool
) -> None:
    """A fresh unit is admitted exactly when the gate `build_runner` builds for its first agent
    step (`build_usage_gate` on the unit's account) allows; one already started is never held
    back by admission, so it goes whenever the round does."""
    other = "platform" if repo == "app" else "app"
    inst, store = workspace(tmp_path, [unit("mine/1", repo), unit("other/1", other)])
    if branched:
        store.set_state("mine/1", RUNNING, branch="spec/mine/1")
    accounts.full = full
    may_start, _resume_at = wiring.build_usage_gate(
        account=claude_account.for_repo(inst.config, repo)
    )
    allowed, _why = may_start()
    round_goes_on = full != {None, PERSONAL}

    admitted = round_of(inst, store)

    assert ("mine/1" in admitted) == (round_goes_on if branched else allowed)
