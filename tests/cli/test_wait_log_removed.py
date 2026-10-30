"""A decision log that was removed is written afresh by the next round, with nothing carried over
from the log that was there (spec: unit-timeline-is-recorded)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.fake_clock import install


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


def blocked_waits(inst: Installation) -> list[dict]:
    path = inst.state_dir / DECISIONS_NAME
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_removed_log_is_written_again_by_the_next_round(tmp_path: Path) -> None:
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([new_unit("first/1"), new_unit("second/1", depends_on=("first/1",))])
    cli.run_round(inst, store, building=(), only=frozenset(), submit=True)
    log = inst.state_dir / DECISIONS_NAME
    assert any(r["unit"] == "second/1" for r in blocked_waits(inst))

    log.unlink()
    cli.run_round(inst, store, building=(), only=frozenset(), submit=True)

    assert [r["reason"] for r in blocked_waits(inst) if r["unit"] == "second/1"] == ["blocked"]
