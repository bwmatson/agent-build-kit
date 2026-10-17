"""A pass step resumes a unit parked for held e2e-test splits once none of them is held, through
the delivery gated units use and once per hold (spec: e2e-runtime-parking)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_holds import remove_hold
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.conftest import make_installation
from tests.parked_split_support import (
    Deliveries,
    hold,
    installation,
    park,
    store_of,
    stub_round,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return installation(tmp_path, acp=False, claude_code=True)


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    return store_of(inst)


@pytest.fixture
def thread(monkeypatch: pytest.MonkeyPatch) -> Deliveries:
    return Deliveries(monkeypatch)


def test_a_unit_whose_splits_are_all_usable_is_resumed_once_by_the_gated_delivery(
    inst: Installation, store: UnitStore, thread: Deliveries
) -> None:
    park(store, splits=("acp",))

    cli.release_split_held(inst, store)

    assert thread.delivered == [("feature/1", "requeue")]
    kept = store.get("feature/1")
    assert kept.parked_splits == ["acp"] and kept.parked_sha == "abc1234", "what the run reads"


def test_a_unit_whose_split_is_still_held_is_left(
    inst: Installation, store: UnitStore, thread: Deliveries
) -> None:
    park(store, splits=("claude_code",))

    cli.release_split_held(inst, store)

    assert thread.delivered == []
    left = store.get("feature/1")
    assert (left.state, left.cause) == (PLANNED, Cause.SPLIT_HELD)


def test_a_unit_waiting_on_two_splits_is_left_until_both_are_usable(
    inst: Installation, store: UnitStore, thread: Deliveries
) -> None:
    park(store, splits=("acp", "claude_code"))

    cli.release_split_held(inst, store)

    assert thread.delivered == [], "never released into a held split"
    assert store.get("feature/1").cause is Cause.SPLIT_HELD


def test_a_unit_in_flight_is_skipped(
    inst: Installation, store: UnitStore, thread: Deliveries
) -> None:
    park(store)
    park(store, "other/1")

    cli.release_split_held(inst, store, in_flight={"feature/1"})

    assert thread.delivered == [("other/1", "requeue")]
    assert store.get("feature/1").cause is Cause.SPLIT_HELD


def test_a_unit_on_a_busy_branch_is_skipped_and_the_rest_run(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = Deliveries(monkeypatch, busy=("feature/1",))
    park(store)
    park(store, "other/1")

    cli.release_split_held(inst, store)

    assert thread.delivered == [("other/1", "requeue")]
    assert store.get("feature/1").cause is Cause.SPLIT_HELD, "tried again on a later pass"


@pytest.fixture
def stubbed_round(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_round(monkeypatch)


@pytest.mark.usefixtures("stubbed_round")
def test_the_round_releases_the_unit_beside_the_gated_ones(
    inst: Installation, store: UnitStore, thread: Deliveries
) -> None:
    park(store)

    cli.run_round(inst, store, building=(), only=frozenset(), submit=False)

    assert thread.delivered == [("feature/1", "requeue")]


@pytest.mark.usefixtures("stubbed_round")
def test_a_step_that_raises_is_logged_and_the_rest_of_the_round_runs(
    inst: Installation,
    store: UnitStore,
    thread: Deliveries,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    park(store)
    later: list[str] = []

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the state file is gone")

    monkeypatch.setattr(cli, "release_split_held", boom)
    monkeypatch.setattr(
        cli,
        "verify_ready",
        lambda inst, units, **kwargs: later.append("verify") or (lambda c: True),
    )

    cli.run_round(inst, store, building=(), only=frozenset(), submit=False)

    assert "the state file is gone" in capsys.readouterr().out
    assert later == ["verify"], "the steps after it still ran"


def test_a_split_configured_not_to_hold_releases_the_unit_although_the_file_holds_it(
    inst: Installation, store: UnitStore, thread: Deliveries
) -> None:
    hold(inst, "acp")
    park(store)

    cli.release_split_held(inst, store)

    assert thread.delivered == [("feature/1", "requeue")]


def test_a_gate_entry_whose_deadline_has_passed_releases_the_unit_on_the_first_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path, acp=None)
    store = store_of(inst)
    thread = Deliveries(monkeypatch)
    park(store)
    hold(inst, "acp", until=datetime.now(UTC) - timedelta(minutes=1))

    cli.release_split_held(inst, store)

    assert thread.delivered == [("feature/1", "requeue")]


def test_a_gate_entry_with_a_deadline_to_come_keeps_the_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path, acp=None)
    store = store_of(inst)
    thread = Deliveries(monkeypatch)
    park(store)
    hold(inst, "acp", until=datetime.now(UTC) + timedelta(hours=1))

    cli.release_split_held(inst, store)

    assert thread.delivered == []
    assert store.get("feature/1").cause is Cause.SPLIT_HELD


def test_a_unit_is_released_once_per_hold_and_not_on_every_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path, acp=None)
    store = store_of(inst)
    thread = Deliveries(monkeypatch)
    park(store)

    cli.release_split_held(inst, store)
    cli.release_split_held(inst, store)
    assert thread.delivered == [("feature/1", "requeue")], "the second pass finds it released"

    hold(inst, "acp")
    park(store)
    cli.release_split_held(inst, store)
    assert len(thread.delivered) == 1, "parked again, and the split is held again"

    assert remove_hold(inst.state_dir, "acp")
    cli.release_split_held(inst, store)
    cli.release_split_held(inst, store)
    assert thread.delivered == [("feature/1", "requeue")] * 2, "once for each hold"


def test_a_split_is_held_or_released_by_the_declarations_of_the_units_own_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acp = {"marker": "runtime_acp"}
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        tests={"e2e_splits": {"acp": acp}},
        repos={
            "platform": {
                "path": str(tmp_path / "checkouts" / "platform"),
                "slug": "example/platform",
            },
            "app": {
                "path": str(tmp_path / "checkouts" / "app"),
                "slug": "example/app",
                "tests": {"e2e_splits": {"acp": {**acp, "hold": False}}},
            },
        },
    )
    store = store_of(inst)
    thread = Deliveries(monkeypatch)
    hold(inst, "acp")
    park(store, "kept/1", repo="platform")
    park(store, "freed/1", repo="app")

    cli.release_split_held(inst, store)

    assert thread.delivered == [("freed/1", "requeue")], "only the repo that releases the split"
    assert store.get("kept/1").cause is Cause.SPLIT_HELD
