"""A unit the gate leaves out waits on the reason `split`, after the reasons that it waits on a
unit, a lease or a backoff and before the usage pause and the ready reasons (spec:
split-start-gate)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_holds import hold_text, repo_holds
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import MERGED, PLANNED
from agent_build_kit.pipeline.vocabulary import WaitReason
from agent_build_kit.pipeline.wait_log import Wait
from tests.parked_split_support import hold
from tests.split_start_support import fresh, gate_round, installation, store_of

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    gate_round(monkeypatch)


def waits_of(
    inst: Installation, store: UnitStore, *, usage_paused: bool = False
) -> dict[str, Wait]:
    return cli.wait_reasons(
        inst,
        store.all(),
        started=set(),
        building=set(),
        only=frozenset(),
        usage_paused=usage_paused,
    )


def test_a_gated_unit_has_the_reason_split_with_the_hold_text_and_its_deadline(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path, acp=None)
    hold(inst, "acp", until=datetime.now(UTC) + timedelta(hours=2))
    store = store_of(inst)
    fresh(store, "gated/1", "acp")

    wait = waits_of(inst, store)["gated/1"]

    held = repo_holds(inst.config, inst.repo("app"), inst.state_dir).held["acp"]
    assert wait.reason is WaitReason.SPLIT == "split"
    assert "waiting for e2e-test split acp" in wait.detail
    assert hold_text(held) in wait.detail
    assert "the usage window is spent" in wait.detail and "until" in wait.detail


def test_a_gated_unit_with_an_unmerged_parent_is_blocked_and_split_once_it_has_merged(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path, acp=True)
    store = store_of(inst)
    fresh(store, "parent/1", "rest")
    fresh(store, "gated/1", "acp", depends_on=("parent/1",))

    before = waits_of(inst, store)["gated/1"]
    store.set_state("parent/1", MERGED, note="merged")
    after = waits_of(inst, store)["gated/1"]

    assert (before.reason, before.waits_on) == (WaitReason.BLOCKED, ("parent/1",))
    assert after.reason is WaitReason.SPLIT


def test_a_gated_unit_under_a_lease_reads_the_lease(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=True)
    store = store_of(inst)
    fresh(store, "gated/1", "acp")
    assert Leases(lease_dir(inst.state_dir)).take("gated/1", "tab:a")

    fresh(store, "gated/2", "acp")

    waits = waits_of(inst, store)

    assert (waits["gated/1"].reason, waits["gated/2"].reason) == (
        WaitReason.LEASE,
        WaitReason.SPLIT,
    )


def test_a_gated_unit_in_a_backoff_reads_the_backoff(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=True)
    store = store_of(inst)
    fresh(store, "gated/1", "acp")
    store.record_step("gated/1", "open_pr")
    store.set_state("gated/1", PLANNED, note="host unavailable", cause=Cause.HOST_UNAVAILABLE)

    fresh(store, "gated/2", "acp")

    waits = waits_of(inst, store)

    assert (waits["gated/1"].reason, waits["gated/2"].reason) == (
        WaitReason.BACKOFF,
        WaitReason.SPLIT,
    )


@pytest.mark.parametrize("usage_paused", [False, True])
def test_the_reason_of_a_gated_unit_is_never_ready_slot_queue_full_or_usage_pause(
    tmp_path: Path, usage_paused: bool
) -> None:
    inst = installation(tmp_path, acp=True, project_limits={"max_units_in_progress": 1})
    store = store_of(inst)
    fresh(store, "gated/1", "acp")

    assert waits_of(inst, store, usage_paused=usage_paused)["gated/1"].reason is WaitReason.SPLIT
