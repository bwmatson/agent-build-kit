"""`abk status` names each outline ready to detail on a line of its own."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit import openspec, run_support
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.cli.test_wait_reasons import workspace_with
from tests.conftest import make_installation
from tests.factories import (
    BIG_PLAN_REASON,
    give_up_plan,
    group_text,
    stored_unit,
    write_changes,
    write_given_up_plans,
    write_outline,
)


def outline_lines(inst: Installation, capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return [line for line in capsys.readouterr().out.splitlines() if "outline" in line]


def test_status_prints_one_line_for_the_ready_outline_and_none_for_the_far_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    inst = make_installation(tmp_path, planning=dict(state_dir="."))
    (inst.changes_dir / "base").mkdir(parents=True)
    (inst.changes_dir / "base" / "tasks.md").write_text("## 1. [app] [unit-test] Work\n")
    store = run_support.store_for(inst)
    store.upsert([stored_unit("base/1", change="base", groups=(1,))])
    store.set_state("base/1", UnitState.RUNNING)
    assert outline_lines(inst, capsys) == []
    write_outline(inst, "next", "Waits on: base group 1 — needs it")
    write_outline(inst, "far", "Waits on: base group 3 — needs it")

    lines = outline_lines(inst, capsys)

    assert len([line for line in lines if "next" in line]) == 1
    assert not [line for line in lines if "far" in line]


def test_status_prints_a_planning_line_only_for_the_active_change_whose_planning_gave_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("agent_build_kit.run_support.current_usage", lambda: None)
    inst = make_installation(tmp_path, planning=dict(state_dir="."))
    write_given_up_plans(inst)

    capsys.readouterr()
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if "planning " in line and "guard planning" not in line
    ]

    assert len(lines) == 1
    assert "big" in lines[0]
    assert "given up" in lines[0]
    assert BIG_PLAN_REASON in lines[0]
    for other in ("edited", "gone", "old"):
        assert not [line for line in lines if other in line]


def test_tags_and_check_refuse_a_needs_line_on_an_outline_or_a_missing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(tmp_path, planning=dict(state_dir="."))
    write_outline(inst, "later")
    needs = (
        "Needs: later group 1 — why\n",
        "Needs: nowhere group 1 — why\n",
        "Needs: base group 9 — why\n",
        "Needs: draft group 1 — why\nNeeds: done group 1 — why\n",
    )
    changes = {
        "feature": "".join(
            f"## {n}. [app] [unit-test] Group {n}\n\n{line}\n- [ ] {n}.1 Test: it.\n\n"
            for n, line in enumerate(needs, start=1)
        ),
        "base": "## 1. [app] [unit-test] Base\n\n- [ ] 1.1 Test: it.\n",
    }
    for name, text in changes.items():
        (inst.changes_dir / name).mkdir(parents=True)
        (inst.changes_dir / name / "tasks.md").write_text(text)
    (inst.changes_dir / "draft").mkdir()
    (inst.changes_dir / "draft" / "proposal.md").write_text("# draft\n")
    (inst.changes_dir / "archive" / "2026-11-01-done").mkdir(parents=True)
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    tags_status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), inst)
    tags_out = capsys.readouterr().out.splitlines()
    check_status = cli.cmd_check(argparse.Namespace(), inst)
    check_out = capsys.readouterr().out.splitlines()

    assert (tags_status, check_status) == (1, 1)
    for out in (tags_out, check_out):
        assert any("later group 1" in line and "Waits on:" in line for line in out)
        assert any("nowhere group 1" in line for line in out)
        assert any("base group 9" in line for line in out)
    assert any("warning" in line and "draft group 1" in line for line in tags_out)
    assert not [line for line in tags_out + check_out if "done" in line]


def test_a_planned_unit_whose_needs_target_has_no_unit_waits_blocked_and_a_met_one_is_ready(
    tmp_path: Path,
) -> None:
    inst = workspace_with(tmp_path, {}, {})
    write_changes(
        inst,
        {
            "feature": group_text((1, "Needs: base group 2 — why")),
            "base": group_text((1, ""), (2, "")),
            "other": group_text((1, "Needs: done group 1 — why")),
        },
    )
    (inst.changes_dir / "archive" / "2026-11-01-done").mkdir(parents=True)
    give_up_plan(inst, "base", "group 2 is too large")
    store = run_support.store_for(inst)
    store.upsert(
        [
            stored_unit("feature/1", change="feature", groups=(1,)),
            stored_unit("other/1", change="other", groups=(1,)),
        ]
    )

    waits = cli.wait_reasons(inst, store.all(), started=set(), building=set(), only=frozenset())

    assert waits["feature/1"].reason is WaitReason.BLOCKED
    assert "base group 2" in waits["feature/1"].detail
    assert "given up" in waits["feature/1"].detail
    assert waits["other/1"].reason is WaitReason.READY
