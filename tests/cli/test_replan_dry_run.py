"""`abk replan --dry-run` asks the planner and prints the units each change would get, writing
nothing (plan-migration)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import PLANNED
from tests.cli.plan_outage_fakes import raises, service
from tests.cli.replan_driver import Replan, answer, enable_review, planned, tasks_md
from tests.factories import stored_unit
from tests.split_sources import snapshot_tree

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLD = tuple(f"feature/{n}" for n in range(1, 5))
# A unit takes the id of its lowest group, so the new unit reuses `feature/1`.
DROPPED = OLD[1:]
LIGHT_600 = answer({**planned("feature/1", (1, 2, 3, 4), lines=600), "review_tier": "light"})


def four_small_units(run: Replan) -> None:
    """`feature`: four planned 150-line units, one group each, and a state file beside them."""
    run.store.upsert(
        [
            stored_unit(uid, change="feature", groups=(n,), estimated_lines=150)
            for n, uid in enumerate(OLD, start=1)
        ]
    )
    run.record("feature")
    (run.inst.state_dir / "notes.txt").write_text("kept\n")


def line_with(out: str, *words: str) -> str:
    return next(line for line in out.splitlines() if all(word in line for word in words))


def test_a_dry_run_lists_the_unit_with_its_tier_and_the_old_units_as_unplanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4))
    enable_review(run)
    four_small_units(run)

    code, out = run.run(capsys, "feature", "--dry-run", reply=LIGHT_600)

    assert code == 0
    unit_line = line_with(out, "feature/1")
    assert "light" in unit_line and "600 of 2000" in unit_line
    for uid in DROPPED:
        assert "unplanned" in line_with(out, uid)
    assert not [line for line in out.splitlines() if "join" in line]
    assert run.calls == 1


def test_the_planner_call_count_is_printed_before_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4))
    enable_review(run)
    four_small_units(run)
    printed_before_call: list[str] = []
    run.runtime.act = lambda request: printed_before_call.append(capsys.readouterr().out)

    run.run(capsys, "feature", "--dry-run", reply=LIGHT_600)

    assert run.calls == 1
    assert "1 planner call" in printed_before_call[0]


def test_a_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4))
    enable_review(run)
    four_small_units(run)
    before = snapshot_tree(run.inst.root)

    code, _ = run.run(capsys, "feature", "--dry-run", reply=LIGHT_600)

    assert code == 0
    assert snapshot_tree(run.inst.root) == before


def test_a_dry_run_writes_nothing_when_the_planner_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4))
    enable_review(run)
    four_small_units(run)
    run.runtime.act = raises(service())
    before = snapshot_tree(run.inst.root)

    run.run(capsys, "feature", "--dry-run")

    assert run.calls == 1
    assert snapshot_tree(run.inst.root) == before


def test_a_dry_run_writes_nothing_when_the_plan_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    enable_review(run)
    run.store.upsert([stored_unit("feature/1", change="feature", groups=(1, 2))])
    run.store.set_state("feature/1", PLANNED, branch="spec/feature/1")
    run.record("feature")
    before = snapshot_tree(run.inst.root)
    reply = answer(planned("feature/a", (1,)), planned("feature/b", (2,)))

    code, _ = run.run(capsys, "feature", "--dry-run", reply=reply)

    assert code == 1
    assert snapshot_tree(run.inst.root) == before
