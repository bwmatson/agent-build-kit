# ruff: noqa: F811 — the imported fixture is requested by name
"""Each admission and each wait for a slot leaves a record that says what it counted and what the
unit's account answered (spec: capacity-checks, admission leaves a record that explains it).

A round is `run_round` over fixture units, as in `test_admission_asks_own_account.py`, whose
stand-in accounts are used here; the records are read back from the state directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.admission_record import (
    ADMISSIONS_NAME,
    AdmissionRecord,
    config_fingerprint,
    read_admissions,
    read_counts,
)
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
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


def test_a_record_carries_the_unit_accounts_usage_decision(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(tmp_path, [unit("one/1", "app")])

    round_of(inst, store)

    [record] = records(inst)
    assert (record.usage.may_start, record.usage.reason) == (True, "plenty")


def test_the_second_admission_of_a_round_counts_the_first_and_the_held_unit_counts_both(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(
        tmp_path, [unit("one/1", "app"), unit("one/2", "app"), unit("one/3", "app")], limit=2
    )

    started = round_of(inst, store)

    assert len(started) == 2
    first, second, held = records(inst)
    assert [each.kind for each in (first, second, held)] == ["admitted", "admitted", "slot"]
    assert first.counted == ()
    assert [each.id for each in second.counted] == [first.unit]
    assert held.unit not in started
    assert [each.id for each in held.counted] == started
    assert (held.limit, len(held.counted)) == (2, 2)
    [counts] = read_counts(inst.state_dir / ADMISSIONS_NAME)
    [slot] = counts.slots
    assert (slot.ids, slot.limit, slot.room) == (tuple(started), 2, 0)


def test_an_account_none_of_whose_units_came_up_for_a_start_is_not_asked_by_the_recorder(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(
        tmp_path,
        [unit("one/1", "app"), unit("busy/1", "platform"), unit("next/1", "platform")],
        limit=1,
    )
    in_review(store, "busy/1", 12)

    assert round_of(inst, store) == ["one/1"]

    assert PERSONAL not in accounts.asked
    [held] = [each for each in records(inst) if each.unit == "next/1"]
    assert (held.kind, held.usage.may_start, held.usage.reason) == (
        "slot",
        None,
        "not asked this round",
    )


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


def test_a_refusal_by_the_account_is_recorded_once_per_episode_with_the_counts_and_the_usage(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(
        tmp_path, [unit("held/1", "platform"), unit("one/1", "app"), unit("two/1", "platform")]
    )
    in_review(store, "held/1", 9)
    accounts.full = {PERSONAL}

    for _ in range(3):
        round_of(inst, store)

    [refusal] = [each for each in records(inst) if each.kind == "usage"]
    assert (refusal.unit, refusal.slot) == ("two/1", PERSONAL)
    assert [each.id for each in refusal.counted] == ["held/1"]
    assert refusal.usage.may_start is False
    assert "weekly usage at 93%" in refusal.usage.reason
    assert refusal.tick
    assert refusal.fingerprint == config_fingerprint(inst)


def test_the_admission_records_are_trimmed_to_the_decision_log_limit(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": ".", "worktree_root": str(tmp_path / "trees")},
        repos={"app": {"path": str(tmp_path / "app"), "slug": "example/app"}},
        retention={"decision_log_mb": 0.002},
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([])
    path = inst.state_dir / ADMISSIONS_NAME
    path.write_text(
        "".join(f'{{"kind": "slot", "padding": "{"x" * 90}", "n": {n}}}\n' for n in range(100))
    )
    assert path.stat().st_size > 2 * 1024

    round_of(inst, store)

    assert path.stat().st_size <= int(0.002 * 1024 * 1024)
    assert path.read_text().splitlines()[-1].endswith('"n": 99}')


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
    # `one/1` is started by this round, so it counts.
    assert (by_slot["default"].ids, by_slot["default"].limit, by_slot["default"].room) == (
        ("one/1",),
        4,
        3,
    )
    assert by_slot[PERSONAL].ids == ("held/1",)
    assert (by_slot[PERSONAL].limit, by_slot[PERSONAL].room) == (4, 3)


def test_a_tick_that_starts_and_refuses_nothing_records_no_counts(
    tmp_path: Path, accounts: Accounts
) -> None:
    inst, store = installation(tmp_path, [])

    round_of(inst, store)

    assert read_counts(inst.state_dir / ADMISSIONS_NAME) == []
