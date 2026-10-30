"""`abk status` and `abk explain` name the change the regression agent wrote and its judgement
(spec: regression-agent).

The change is a folder with the proposal the agent writes; the record and the unit are as the
pipeline leaves them when a unit waits on it.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import Flake, flake_record
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.conftest import make_installation
from tests.factories import stored_unit

TEST = "tests/test_widget.py::test_renders_the_label"
FIX = "fix-test-tests-test-widget-py-test-renders-the-label"
JUDGEMENT = "the implementation is wrong"
PROPOSAL = f"""\
## Why

`{TEST}` fails because the label is read at import time.

- Cause: the label is read at import time.
- Since: commit 3f9c2a1d, 2026-02-11.
- Base: 3f9c2a1d0b7e
- Judgement: {JUDGEMENT}.
"""
TASKS = f"""\
# Tasks

## 1. [app] [unit-test] Build the feature

Needs: {FIX} group 1 — failing test {TEST}

- [ ] 1.1 Test: it works
- [ ] 1.2 Make it work
"""


def waiting(tmp_path: Path) -> tuple[Installation, UnitStore]:
    """A unit gated on the fix change of a failing test, and the record of that failure."""
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    fix = workspace.changes_dir / FIX
    fix.mkdir(parents=True)
    (fix / "proposal.md").write_text(PROPOSAL)
    own = workspace.changes_dir / "feature"
    own.mkdir(parents=True)
    (own / "tasks.md").write_text(TASKS)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("feature/1", change="feature", groups=(1,))])
    store.set_state(
        "feature/1",
        PLANNED,
        note=f"waiting for the fix of the failing test {TEST}",
        cause=Cause.GATED,
    )
    flake_record(workspace).append(
        Flake(
            test=TEST,
            unit="feature/1",
            command="uv run pytest -n auto -q",
            output="FAILED",
            at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
            change=FIX,
            failing=True,
        )
    )
    return workspace, store


def test_status_names_the_change_and_the_judgement_of_a_failing_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, _ = waiting(tmp_path)
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert cli.cmd_status(argparse.Namespace(), workspace) == 0

    lines = capsys.readouterr().out.splitlines()
    row = next(line for line in lines if TEST in line and FIX in line)
    assert JUDGEMENT in row


def test_explain_names_the_change_and_the_judgement_a_unit_waits_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, _ = waiting(tmp_path)

    assert cmd_explain(argparse.Namespace(unit="feature/1", at=None), workspace) == 0

    out = capsys.readouterr().out
    assert FIX in out
    assert JUDGEMENT in out
