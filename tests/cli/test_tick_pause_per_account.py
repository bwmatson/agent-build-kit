"""A pass goes on starting the accounts the model has not refused (spec: capacity-checks, one
pause per account).

`app` runs on the default account and `platform` on `personal`. A build is a stand-in whose script
raises the model's refusal; the pass is `cmd_tick`. A unit that needs `gate/1` is ready only once
the gate is in review, which its script holds back until the refusal is recorded, so it is started
(or not) by a later round of the same pass.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.pause import is_paused
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.pipeline.usage_guard import RateLimited
from tests.cli.test_admission_asks_own_account import (  # noqa: F401 — fixtures
    PERSONAL,
    Accounts,
    accounts,
    isolated,
    unit,
    workspace,
)
from tests.tick_pass import Builder
from tests.waiting import wait_for

pytestmark = pytest.mark.usefixtures("scripted_engine")

WAIT = 30


def refusal() -> None:
    raise RateLimited("usage limit reached", resets_at=datetime.now(UTC) + timedelta(hours=2))


def after_gate(uid: str, repo: str) -> StoredUnit:
    return unit(uid, repo).model_copy(update={"depends_on": ("gate/1",)})


def tick(inst) -> int:
    return cli.cmd_tick(argparse.Namespace(dry_run=False), inst)


def test_a_refusal_of_one_account_mid_pass_leaves_the_other_accounts_units_to_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accounts: Accounts,  # noqa: F811
) -> None:
    inst, store = workspace(
        tmp_path,
        [
            unit("one/1", "app"),
            unit("gate/1", "platform"),
            after_gate("again/1", "app"),
            after_gate("two/1", "platform"),
        ],
    )
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    builder = Builder(store)
    monkeypatch.setattr(cli, "build_runner", builder)
    marker = inst.state_dir / "paused.json"
    builder.scripts["one/1"] = refusal
    builder.scripts["gate/1"] = lambda: wait_for(
        marker.exists, what="the default account's pause", timeout=WAIT
    )

    tick(inst)

    assert "two/1" in builder.started
    assert store.get("two/1").state == IN_REVIEW
    assert "again/1" not in builder.started
    assert store.get("again/1").state == PLANNED
    assert is_paused(marker) is not None
    assert is_paused(inst.state_dir / f"paused.{PERSONAL}.json") is None


def test_a_pass_starts_nothing_more_once_every_account_has_been_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accounts: Accounts,  # noqa: F811
) -> None:
    inst, store = workspace(
        tmp_path,
        [
            unit("one/1", "app"),
            unit("two/1", "platform"),
            unit("gate/1", "platform"),
            after_gate("again/1", "app"),
            after_gate("more/1", "platform"),
        ],
    )
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    builder = Builder(store)
    monkeypatch.setattr(cli, "build_runner", builder)
    default_marker = inst.state_dir / "paused.json"
    personal_marker = inst.state_dir / f"paused.{PERSONAL}.json"
    builder.scripts["one/1"] = refusal

    def refused_after_the_default_account() -> None:
        wait_for(default_marker.exists, what="the default account's pause", timeout=WAIT)
        refusal()

    builder.scripts["two/1"] = refused_after_the_default_account
    builder.scripts["gate/1"] = lambda: wait_for(
        personal_marker.exists, what="the personal account's pause", timeout=WAIT
    )

    tick(inst)

    assert sorted(builder.started) == ["gate/1", "one/1", "two/1"]
    assert {store.get(uid).state for uid in ("again/1", "more/1")} == {PLANNED}
