"""A unit the gate left out starts in the first round that finds its split no longer held, with
no round between (spec: split-start-gate)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_holds import remove_hold
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.parked_split_support import hold
from tests.split_start_support import fresh, gate_round, installation, round_ids, store_of

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def stubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    gate_round(monkeypatch)


def gated_unit(inst: Installation) -> UnitStore:
    store = store_of(inst)
    fresh(store, "gated/1", "acp")
    return store


def test_the_first_round_after_a_release_starts_the_unit(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=None)
    hold(inst, "acp")
    store = gated_unit(inst)
    assert round_ids(inst, store) == [], "held until released"

    assert remove_hold(inst.state_dir, "acp")

    assert round_ids(inst, store) == ["gated/1"]


def test_the_first_round_after_the_configured_hold_is_removed_starts_the_unit(
    tmp_path: Path,
) -> None:
    held = installation(tmp_path, acp=True)
    store = gated_unit(held)
    assert round_ids(held, store) == []

    released = installation(tmp_path, acp=None)

    assert round_ids(released, store) == ["gated/1"]


def test_the_first_round_after_a_gates_entry_is_removed_starts_the_unit(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=None)
    hold(inst, "acp", until=datetime.now(UTC) + timedelta(hours=1))
    store = gated_unit(inst)
    assert round_ids(inst, store) == []

    assert remove_hold(inst.state_dir, "acp")

    assert round_ids(inst, store) == ["gated/1"]


def test_a_gates_entry_whose_deadline_has_passed_does_not_gate_the_unit(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=True, claude_code=None)
    hold(inst, "claude_code", until=datetime.now(UTC) - timedelta(seconds=1))
    store = gated_unit(inst)
    fresh(store, "expired/1", "claude_code")

    assert round_ids(inst, store) == ["expired/1"], "the expired entry starts, the live one waits"
