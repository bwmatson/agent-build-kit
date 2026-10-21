"""`abk status` counts the stale plans and names them, and says nothing when none is."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import activate_with, stored_unit


def record(sizing: str) -> dict:
    return {"hash": "a-hash", "sizing": sizing, "attempts": 0, "ok": True}


def test_status_counts_and_names_the_stale_plans_and_is_silent_when_none_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    activate_with(review={"enabled": True})
    UnitStore(tmp_path / "units.json").upsert([stored_unit("gamma/1", change="gamma")])
    for change in ("alpha", "beta", "gamma"):
        (inst.changes_dir / change).mkdir(parents=True)
        (inst.changes_dir / change / "tasks.md").write_text("# Tasks\n")
    (inst.changes_dir / "archive" / "2026-01-01-old").mkdir(parents=True)
    (inst.changes_dir / "archive" / "2026-01-01-old" / "tasks.md").write_text("# Tasks\n")
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    plans = tmp_path / "planned.json"
    plans.write_text(
        json.dumps(
            {
                "alpha": record("an-older-digest"),
                "beta": record(""),
                "gamma": record(cli.sizing_digest()),
                "gone": record(""),
                "2026-01-01-old": record(""),
            }
        )
    )

    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if "stale" in line)
    assert re.search(r"\b2 plan\(s\) stale", line)
    assert "alpha" in line
    assert "beta" in line
    assert "gamma" not in line

    plans.write_text(json.dumps({"alpha": record(cli.sizing_digest())}))

    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    assert "stale" not in capsys.readouterr().out
