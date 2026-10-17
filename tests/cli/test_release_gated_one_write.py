"""`release_gated` rewrites the cause in one write when the thread declines the delivery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.conftest import make_installation
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

DECLINES = "declined/1"
TAKES = "taken/1"


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )


@pytest.fixture
def store(inst: Installation, monkeypatch: pytest.MonkeyPatch) -> UnitStore:
    store = UnitStore(inst.state_dir / "units.json")
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)
    monkeypatch.setattr(
        cli,
        "resume_thread",
        lambda inst, unit, kind, **kwargs: object() if unit.id == TAKES else None,
    )
    for uid in (DECLINES, TAKES):
        store.upsert([stored_unit(uid, change=uid.partition("/")[0])])
        store.set_state(uid, PLANNED, branch=f"spec/{uid}", cause=Cause.GATED)
        store.set_gated_requeue(uid, RequeueReason.RESUME)
    return store


def test_a_declined_delivery_is_one_write_and_a_taken_one_clears_the_requeue(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[Any, Any]] = []
    for name in ("set_state", "set_gated_requeue"):
        real = getattr(store, name)

        def spy(*args: Any, real: Any = real, **kwargs: Any) -> None:
            real(*args, **kwargs)
            now = store.get(DECLINES)
            seen.append((now.cause, now.gated_requeue))

        monkeypatch.setattr(store, name, spy)
    before = len(store.history(DECLINES))

    cli.release_gated(inst, store)

    declined = store.get(DECLINES)
    assert len(declined.history) == before + 1
    assert declined.history[-1]["cause"] == Cause.REQUEUED.value
    assert declined.gated_requeue is None
    assert (Cause.GATED, None) not in seen, "never gated without its requeue"
    assert store.get(TAKES).gated_requeue is None, "a delivery clears it too"
