"""`abk requeue` tells the thread why by a `RequeueReason`, not by a word the thread parses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import dump
from agent_build_kit.pipeline.unit_store import RequeueReason, UnitStore
from tests.conftest import make_installation
from tests.factories import unit


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> UnitStore:
    inst = make_installation(tmp_path / "planning")
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    monkeypatch.chdir(inst.root)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([unit("add-marker/1")])
    store.set_state("add-marker/1", "failed", branch="spec/add-marker/1")
    store.set_feedback("add-marker/1", "a saved failure")
    return store


@pytest.mark.parametrize(
    ("flags", "reason"),
    [
        ([], RequeueReason.RESUME),
        (["--rework"], RequeueReason.FROM_FAILURE),
        (["--restart"], RequeueReason.RESTART),
    ],
)
def test_each_requeue_mode_is_delivered_as_its_reason(
    store: UnitStore, monkeypatch: pytest.MonkeyPatch, flags: list[str], reason: RequeueReason
) -> None:
    delivered: list[dict[str, Any]] = []

    def resume_thread(inst, unit, kind, **kwargs):
        delivered.append({"kind": kind, **kwargs})
        return None

    monkeypatch.setattr(cli, "resume_thread", resume_thread)

    assert main(["requeue", "add-marker/1", *flags]) == 0

    (call,) = delivered
    assert call["kind"] == "requeue"
    assert call["requeue"] is reason
