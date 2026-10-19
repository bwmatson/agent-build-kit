"""`abk replan` releases a parked unit whose group's `Split:` changed, right after it plans, and
a dry run says what a pass would release (spec: a-parked-unit-follows-its-groups-split)."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import PLANNED
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.parked_split_support import park, stub_round
from tests.split_changed_support import UNIT, Reworks
from tests.split_workspace import DECLARED, group, tasks_text

pytestmark = pytest.mark.usefixtures("scripted_engine")

SPLITS = dict(DECLARED, acp=dict(DECLARED["acp"], hold=True))
PLAN = answer(planned("other/1", (1,)))


def parked_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    """`feature` planned, its one unit parked on the held `acp`, its group now `claude_code`."""
    run = Replan(
        tmp_path,
        monkeypatch,
        tests=dict(e2e_splits=SPLITS),
        feature=tasks_text(group(1, "Split: claude_code")),
        other=tasks_md(1),
    )
    park(run.store, splits=("acp",), split="acp")
    run.record("feature")
    return run


def test_a_replan_prints_a_line_naming_the_unit_and_both_splits_and_releases_it_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = parked_run(tmp_path, monkeypatch)
    thread = Reworks(monkeypatch, run.store)

    code, out = run.run(capsys, "other", reply=PLAN)

    assert code == 0, out
    [line] = [x for x in out.splitlines() if UNIT in x and "acp" in x and "claude_code" in x]
    assert out.index("planning") < out.index(line), "after the plan"
    assert [call["unit"] for call in thread.calls] == [UNIT]
    assert run.store.get(UNIT).split == "claude_code"

    again, out_again = run.run(capsys, "other", reply=PLAN)

    assert again == 0
    assert "claude_code" not in out_again, "nothing parked, nothing new"
    assert len(thread.calls) == 1


def test_a_dry_run_says_it_would_rework_the_unit_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = parked_run(tmp_path, monkeypatch)
    stub_round(monkeypatch)
    thread = Reworks(monkeypatch, run.store)
    before = run.store.get(UNIT)
    capsys.readouterr()

    assert cli.cmd_tick(argparse.Namespace(dry_run=True), run.inst) == 0

    lines = capsys.readouterr().out.splitlines()
    [would] = [x for x in lines if UNIT in x and "would rework" in x]
    assert "acp" in would and "claude_code" in would
    assert thread.calls == []
    assert run.store.get(UNIT) == before and before.state == PLANNED
