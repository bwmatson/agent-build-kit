# ruff: noqa: F811 — the imported fixture is requested by name
"""Each admission and each wait for a slot leaves a record that says what it counted and what the
unit's account answered (spec: capacity-checks, admission leaves a record that explains it).

A round is `run_round` over fixture units, as in `test_admission_asks_own_account.py`, whose
stand-in accounts are used here; the records are read back from the state directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import wiring
from agent_build_kit.pipeline.admission_record import (
    ADMISSIONS_NAME,
    AdmissionRecord,
    config_fingerprint,
    read_admissions,
    read_counts,
)
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.pipeline.usage_guard import Decision
from tests.cli.test_admission_asks_own_account import (  # noqa: F401 — fixtures
    PERSONAL,
    Accounts,
    accounts,
    isolated,
    round_of,
    unit,
)
from tests.conftest import make_installation

APP_HAS_SPEC_BRANCH = "spec/busy/1"


class Readings(Accounts):
    """Accounts whose decisions say what they were made on."""

    def decide(self, account: claude_account.Account | None) -> Decision:
        decision = super().decide(account)
        return decision.model_copy(
            update={
                "source": "usage cache",
                "age_seconds": 42.0,
                "threshold": 93.0,
                "ramp": 71.5,
                "estimate": True,
                "estimate_starts": 2,
            }
        )


@pytest.fixture
def readings(monkeypatch: pytest.MonkeyPatch) -> Readings:
    answers = Readings()
    monkeypatch.setattr(cli, "decide_start", answers)
    monkeypatch.setattr(wiring, "decide_start", answers)
    return answers


def installation(
    tmp_path: Path, units: list[StoredUnit], *, limit: int = 5, per_account: bool = True
) -> tuple[Installation, UnitStore]:
    """`app` on the default account and `platform` on `personal` (or, with `per_account` off,
    both counted per project), each slot allowing `limit` units in progress."""
    named = {"account": PERSONAL} if per_account else {}
    runtimes = (
        {"claude_code": {"accounts": {PERSONAL: {"config_dir": str(tmp_path / "p")}}}}
        if per_account
        else {}
    )
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": ".", "worktree_root": str(tmp_path / "trees")},
        project_limits={"max_units_in_progress": limit},
        repos={
            "app": {"path": str(tmp_path / "app"), "slug": "example/app"},
            "platform": {"path": str(tmp_path / "platform"), "slug": "example/platform", **named},
        },
        runtimes=runtimes,
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert(units)
    return inst, store


def in_review(store: UnitStore, uid: str, pr: int) -> None:
    store.set_state(uid, IN_REVIEW, pr=pr, branch=f"spec/{uid}")


def records(inst: Installation) -> list[AdmissionRecord]:
    return read_admissions(inst.state_dir / ADMISSIONS_NAME)


def test_an_admission_records_the_slot_the_limit_and_the_units_counted_with_why(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(tmp_path, [unit("busy/1", "app"), unit("one/1", "app")], limit=3)
    in_review(store, "busy/1", 12)

    assert round_of(inst, store) == ["one/1"]

    [record] = records(inst)
    assert (record.kind, record.unit, record.slot, record.limit) == (
        "admitted",
        "one/1",
        "default",
        3,
    )
    [counted] = record.counted
    assert (counted.id, counted.state) == ("busy/1", "in_review")
    assert "12" in counted.why


def test_a_counted_unit_with_only_a_branch_says_the_branch_is_why_it_counts(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(tmp_path, [unit("busy/1", "app"), unit("one/1", "app")])
    store.set_state("busy/1", PLANNED, branch=APP_HAS_SPEC_BRANCH)

    round_of(inst, store)

    [record] = [each for each in records(inst) if each.unit == "one/1"]
    [counted] = record.counted
    assert counted.id == "busy/1"
    assert APP_HAS_SPEC_BRANCH in counted.why


def test_a_unit_of_a_named_account_is_recorded_under_the_accounts_label(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(tmp_path, [unit("two/1", "platform")])

    round_of(inst, store)

    [record] = records(inst)
    assert (record.unit, record.slot) == ("two/1", PERSONAL)


def test_without_accounts_the_slot_is_the_project(tmp_path: Path, accounts: Accounts) -> None:
    inst, store = installation(tmp_path, [unit("one/1", "app")], per_account=False)

    round_of(inst, store)

    [record] = records(inst)
    assert record.slot == "app"


def test_a_record_carries_the_unit_accounts_usage_decision_with_its_reading(
    tmp_path: Path, readings: Readings
) -> None:
    inst, store = installation(tmp_path, [unit("one/1", "app")])

    round_of(inst, store)

    [record] = records(inst)
    usage = record.usage
    assert (usage.may_start, usage.reason) == (True, "plenty")
    assert usage.source == "usage cache"
    assert usage.age_seconds == 42.0
    assert (usage.threshold, usage.ramp) == (93.0, 71.5)
    assert (usage.estimate, usage.estimate_starts) == (True, 2)


def test_a_wait_for_a_slot_records_the_ids_counted_against_the_limit(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(tmp_path, [unit("busy/1", "app"), unit("next/1", "app")], limit=1)
    in_review(store, "busy/1", 12)

    assert round_of(inst, store) == []

    [record] = records(inst)
    assert (record.kind, record.unit, record.slot, record.limit) == ("slot", "next/1", "default", 1)
    assert [each.id for each in record.counted] == ["busy/1"]
    assert record.usage.may_start is True


def test_a_slot_wait_is_recorded_again_only_when_the_counted_set_changes(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(tmp_path, [unit("busy/1", "app"), unit("next/1", "app")], limit=1)
    in_review(store, "busy/1", 12)
    round_of(inst, store)
    round_of(inst, store)
    assert len(records(inst)) == 1

    store.upsert([unit("busy/2", "app")])
    in_review(store, "busy/2", 13)
    round_of(inst, store)

    latest = records(inst)[-1]
    assert len(records(inst)) == 2
    assert [each.id for each in latest.counted] == ["busy/1", "busy/2"]


def test_the_records_of_a_round_share_a_tick_and_carry_the_configuration_fingerprint(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(
        tmp_path, [unit("one/1", "app"), unit("two/1", "platform"), unit("three/1", "platform")]
    )

    round_of(inst, store)

    found = records(inst)
    assert len(found) == 3
    assert len({each.tick for each in found}) == 1
    assert found[0].tick
    assert {each.fingerprint for each in found} == {config_fingerprint(inst)}


def test_the_fingerprint_is_stable_and_changes_with_the_overlay_and_with_a_file_touched(
    tmp_path: Path,
) -> None:
    inst, _store = installation(tmp_path, [])
    before = config_fingerprint(inst)
    assert config_fingerprint(inst) == before

    overlay = inst.root / "abk.local.yaml"
    overlay.write_text("project_limits:\n  max_units_in_progress: 4\n")
    os.utime(overlay, (1_000_000_000, 1_000_000_000))
    written = config_fingerprint(inst)
    assert written != before

    os.utime(overlay, (1_000_000_100, 1_000_000_100))
    assert config_fingerprint(inst) != written


def test_a_unit_refused_by_its_account_has_one_usage_pause_entry_per_episode(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(tmp_path, [unit("one/1", "app"), unit("two/1", "platform")])
    accounts.full = {PERSONAL}

    for _ in range(3):
        round_of(inst, store)

    [paused] = [e for e in store.history("two/1") if e.get("event") == "usage_pause"]
    assert paused["account"] == PERSONAL
    assert "weekly usage at 93%" in paused["reason"]
    assert not [e for e in store.history("two/1") if e.get("event") == "usage_resume"]


def test_the_resume_is_one_entry_and_a_second_refusal_is_a_new_episode(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(tmp_path, [unit("one/1", "app"), unit("two/1", "platform")])
    accounts.full = {PERSONAL}
    round_of(inst, store)
    accounts.full = set()
    round_of(inst, store)
    round_of(inst, store)

    resumed = [e for e in store.history("two/1") if e.get("event") == "usage_resume"]
    assert [e["account"] for e in resumed] == [PERSONAL]

    accounts.full = {PERSONAL}
    round_of(inst, store)
    events = [
        e["event"] for e in store.history("two/1") if str(e.get("event", "")).startswith("usage_")
    ]
    assert events == ["usage_pause", "usage_resume", "usage_pause"]


def test_a_tick_that_starts_or_refuses_records_each_accounts_ids_limit_and_room(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(
        tmp_path,
        [unit("held/1", "platform"), unit("one/1", "app"), unit("two/1", "platform")],
        limit=4,
    )
    in_review(store, "held/1", 9)
    accounts.full = {PERSONAL}

    round_of(inst, store)

    [counts] = read_counts(inst.state_dir / ADMISSIONS_NAME)
    assert counts.tick
    assert counts.fingerprint == config_fingerprint(inst)
    by_slot = {each.slot: each for each in counts.slots}
    assert (by_slot["default"].ids, by_slot["default"].limit, by_slot["default"].room) == ((), 4, 4)
    assert by_slot[PERSONAL].ids == ("held/1",)
    assert (by_slot[PERSONAL].limit, by_slot[PERSONAL].room) == (4, 3)


def test_a_tick_that_starts_and_refuses_nothing_records_no_counts(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(tmp_path, [])

    round_of(inst, store)

    assert read_counts(inst.state_dir / ADMISSIONS_NAME) == []
