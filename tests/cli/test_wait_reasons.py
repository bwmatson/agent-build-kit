"""Every unit that is not running has one reason for it (spec: unit-timeline-is-recorded).

The reasons come from the facts the pass already decides on, through `wait_reasons`;
`run_round` still starts the units it started without them.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Collection
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.pause import PAUSE_MARKER, pause_until
from agent_build_kit.pipeline.run_log import run_log_dir
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, MERGED, PLANNED, RUNNING
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.vocabulary import WaitReason
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME, Wait
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.fake_clock import install
from tests.pipeline.test_run_log import start_run

Setup = Callable[[UnitStore, Installation], None]


def reviewed(store: UnitStore, uid: str) -> None:
    store.set_state(uid, RUNNING, branch=f"spec/{uid}")
    store.set_state(uid, IN_REVIEW, pr=7)


def blocked(store: UnitStore, inst: Installation) -> None:
    store.upsert([new_unit("first/1"), new_unit("second/1", depends_on=("first/1",))])


def queue_full(store: UnitStore, inst: Installation) -> None:
    store.upsert([new_unit("busy/1"), new_unit("second/1")])
    reviewed(store, "busy/1")


def in_review(store: UnitStore, inst: Installation) -> None:
    store.upsert([new_unit("second/1")])
    reviewed(store, "second/1")


def held(store: UnitStore, inst: Installation) -> None:
    store.upsert([new_unit("second/1")])
    store.set_state("second/1", HELD, note="a person took over")


def failed(store: UnitStore, inst: Installation) -> None:
    store.upsert([new_unit("second/1")])
    store.set_state("second/1", FAILED, note="stopped")


def leased(store: UnitStore, inst: Installation) -> None:
    store.upsert([new_unit("second/1")])
    assert Leases(lease_dir(inst.state_dir)).take("second/1", "tab:a")


def in_backoff(store: UnitStore, inst: Installation) -> None:
    store.upsert([new_unit("second/1")])
    store.record_step("second/1", "open_pr")
    store.set_state("second/1", PLANNED, note="host unavailable", cause=Cause.HOST_UNAVAILABLE)


def depth_held(store: UnitStore, inst: Installation) -> None:
    store.upsert([new_unit("first/1"), new_unit("second/1", depends_on=("first/1",))])
    store.set_state("second/1", HELD, note="stack too deep", held_by=HeldBy.DEPTH)


def startable(store: UnitStore, inst: Installation) -> None:
    store.upsert([new_unit("second/1")])


# What each setup leaves `second/1` waiting for, and the limits of the pass it is judged in.
CASES = [
    pytest.param(blocked, WaitReason.BLOCKED, {}, id="blocked"),
    pytest.param(queue_full, WaitReason.QUEUE_FULL, {"max_units_in_progress": 1}, id="queue-full"),
    pytest.param(in_review, WaitReason.WAITING_REVIEW, {}, id="in-review"),
    pytest.param(held, WaitReason.NEEDS_PERSON, {}, id="held"),
    pytest.param(failed, WaitReason.NEEDS_PERSON, {}, id="failed"),
    pytest.param(depth_held, WaitReason.BLOCKED, {}, id="held-for-depth"),
    pytest.param(leased, WaitReason.LEASE, {}, id="leased"),
    pytest.param(in_backoff, WaitReason.BACKOFF, {}, id="backoff"),
    pytest.param(startable, WaitReason.READY, {}, id="startable"),
]


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))


def installation(tmp_path: Path, **limits: int) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_concurrent_stacks": 2, "max_units_in_progress": 50, **limits},
    )


def waits_of(
    tmp_path: Path,
    setup: Setup,
    *,
    building: Collection[str] = (),
    started: Collection[str] = (),
    usage_paused: bool = False,
    limits: dict[str, int] | None = None,
) -> dict[str, Wait]:
    inst = installation(tmp_path, **(limits or {}))
    store = UnitStore(tmp_path / "units.json")
    setup(store, inst)
    return cli.wait_reasons(
        inst,
        store.all(),
        started=set(started),
        building=set(building),
        only=frozenset(),
        usage_paused=usage_paused,
    )


def test_slot_and_usage_pause_equal_the_buckets_the_ledger_already_holds(tmp_path: Path) -> None:
    assert WaitReason.SLOT == spans.SLOT == "slot"
    assert WaitReason.USAGE_PAUSE == spans.USAGE_PAUSE == "usage_pause"

    waits = waits_of(tmp_path, startable, usage_paused=True)

    assert waits["second/1"].reason == "usage_pause"


@pytest.mark.parametrize(("setup", "reason", "limits"), CASES)
def test_a_unit_that_is_not_running_gets_the_one_reason_for_what_holds_it(
    tmp_path: Path, setup: Setup, reason: WaitReason, limits: dict[str, int]
) -> None:
    waits = waits_of(tmp_path, setup, limits=limits)

    assert waits["second/1"].reason is reason


def test_a_ready_unit_without_a_free_slot_waits_for_one(tmp_path: Path) -> None:
    def setup(store: UnitStore, inst: Installation) -> None:
        store.upsert([new_unit("busy/1"), new_unit("second/1")])
        store.set_state("busy/1", RUNNING, branch="spec/busy/1")

    waits = waits_of(tmp_path, setup, building={"busy/1"}, limits={"max_concurrent_stacks": 1})

    assert waits["second/1"].reason is WaitReason.SLOT
    assert "busy/1" not in waits, "a unit that is running has no reason"


def test_a_startable_unit_waits_for_the_usage_pause_when_the_pipeline_is_paused(
    tmp_path: Path,
) -> None:
    waits = waits_of(tmp_path, startable, usage_paused=True)

    assert waits["second/1"].reason is WaitReason.USAGE_PAUSE


def test_a_unit_blocked_on_a_prerequisite_names_what_it_waits_on(tmp_path: Path) -> None:
    waits = waits_of(tmp_path, blocked)

    assert waits["second/1"].waits_on == ("first/1",)
    assert waits["first/1"].reason is WaitReason.READY
    assert waits["first/1"].waits_on == ()


def test_finished_units_have_no_reason(tmp_path: Path) -> None:
    def setup(store: UnitStore, inst: Installation) -> None:
        store.upsert([new_unit("done/1"), new_unit("second/1")])
        store.set_state("done/1", MERGED, note="merged")

    assert set(waits_of(tmp_path, setup)) == {"second/1"}


@pytest.mark.parametrize(("setup", "reason", "limits"), CASES)
def test_a_round_starts_the_units_it_started_before_reasons_were_computed(
    tmp_path: Path, setup: Setup, reason: WaitReason, limits: dict[str, int]
) -> None:
    inst = installation(tmp_path, **limits)
    store = UnitStore(tmp_path / "units.json")
    setup(store, inst)

    ready = cli.run_round(inst, store, building=(), only=frozenset(), submit=True)

    expected = ["second/1"] if reason is WaitReason.READY else []
    assert [unit.id for unit in ready if unit.id == "second/1"] == expected
    logged = [r for r in decisions(inst) if r["unit"] == "second/1"]
    # What it started has no reason; what it did not is logged under the one reason.
    assert [r["reason"] for r in logged] == ([] if expected else [reason.value])


def decisions(inst: Installation) -> list[dict]:
    path = inst.state_dir / "decisions.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_a_round_that_started_nothing_for_want_of_a_choice_records_no_usage_pause(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    leased(store, inst)
    store.upsert([new_unit("other/1")])

    cli.run_round(inst, store, building=(), only=frozenset({"second/1"}), submit=True)

    reasons = {r["unit"]: r["reason"] for r in decisions(inst)}
    assert reasons == {"second/1": "lease"}, "`other/1` is left out by --only, not paused"


def test_a_round_under_the_models_rate_limit_pause_records_usage_pause_for_a_startable_unit(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    startable(store, inst)
    pause_until(
        spans.clock.now() + timedelta(hours=3),
        reason="the model refused",
        marker=inst.state_dir / PAUSE_MARKER,
        kind="rate_limit",
    )

    cli.run_round(inst, store, building=(), only=frozenset(), submit=True)

    assert [(r["unit"], r["reason"]) for r in decisions(inst)] == [("second/1", "usage_pause")]


def test_a_round_the_usage_guard_refuses_records_usage_pause_for_a_startable_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    startable(store, inst)
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r: Decision(may_start=False, reason="session usage at 90%")
    )

    ready = cli.run_round(inst, store, building=(), only=frozenset(), submit=True)

    assert ready == []
    assert [(r["unit"], r["reason"]) for r in decisions(inst)] == [("second/1", "usage_pause")]


def test_a_unit_left_out_by_only_keeps_its_wait_open(tmp_path: Path) -> None:
    inst = installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    leased(store, inst)
    cli.run_round(inst, store, building=(), only=frozenset(), submit=True)

    cli.run_round(inst, store, building=(), only=frozenset({"other/1"}), submit=True)

    assert [r["reason"] for r in decisions(inst) if r["unit"] == "second/1"] == ["lease"]


def test_a_started_unit_that_reached_review_is_judged_by_its_stored_state(tmp_path: Path) -> None:
    waits = waits_of(tmp_path, in_review, started={"second/1"})

    assert waits["second/1"].reason == WaitReason.WAITING_REVIEW


def test_a_round_logs_needs_person_for_a_unit_this_pass_started_and_a_hold_ended(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    held(store, inst)
    readmit = cli._Readmission()
    # Started before the hold was recorded: the hold is the last entry of its history.
    readmit.started["second/1"] = len(store.get("second/1").history) - 1

    cli.run_round(inst, store, building=(), only=frozenset(), submit=True, readmit=readmit)

    assert [(r["unit"], r["reason"]) for r in decisions(inst)] == [("second/1", "needs_person")]


def test_a_round_that_starts_nothing_dates_when_a_unit_became_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([new_unit("first/1"), new_unit("second/1", depends_on=("first/1",))])
    store.set_state("first/1", FAILED, note="stopped")
    store.upsert([new_unit("third/1")])
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r: Decision(may_start=False, reason="session usage at 90%")
    )

    cli.run_round(inst, store, building=(), only=frozenset(), submit=True)

    assert store.get("third/1").ready_at is not None
    assert store.get("second/1").ready_at is None


def test_a_round_bounds_the_logs_by_the_installations_retention(tmp_path: Path) -> None:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        retention={"decision_log_mb": 0.002, "unit_log_days": 3},
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([new_unit("second/1")])
    lines = [
        json.dumps({"at": "x", "unit": "old/1", "reason": "blocked", "n": n}) for n in range(200)
    ]
    log = inst.state_dir / DECISIONS_NAME
    log.write_text("".join(f"{line}\n" for line in lines))
    old = run_log_dir(inst.state_dir)
    start_run(old, "add-marker/1").close("open")
    (path,) = old.iterdir()
    stamp = (datetime.now(UTC) - timedelta(days=4)).timestamp()
    os.utime(path, (stamp, stamp))
    (inst.state_dir / LEDGER_NAME).write_text(
        json.dumps({"kind": "summary", "unit": "add-marker/1", "change": "add-marker"}) + "\n"
    )

    cli.run_round(inst, store, building=(), only=frozenset(), submit=True)

    kept = log.read_text().splitlines()
    assert log.stat().st_size <= 0.002 * 1024 * 1024
    assert lines[-1] in kept and lines[0] not in kept, "the newest lines stay"
    assert not path.exists(), "four days old is past the three the installation sets"


def test_a_decision_log_that_cannot_be_trimmed_still_dates_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        retention={"decision_log_mb": 0.001},
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([new_unit("second/1")])
    (inst.state_dir / DECISIONS_NAME).write_text("x" * 5000 + "\n")

    def full_disk(self: Path, data: bytes) -> int:
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "write_bytes", full_disk)
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r: Decision(may_start=False, reason="session usage at 90%")
    )
    cli.run_round(inst, store, building=(), only=frozenset(), submit=True)

    assert store.get("second/1").ready_at is not None
