"""A tag edited under a started unit is reported, never applied, and never recorded as done."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import FAILED
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

RETAGGED = tasks_md(1).replace("[tier1]", "[tier2]")


def failed_unit_with_retagged_group(run: Replan) -> str:
    """A failed unit, its change recorded as planned, then its group re-tagged; the old hash."""
    run.store.upsert([unit("feature/1", change="feature", groups=(1,))])
    run.store.set_state("feature/1", FAILED, branch="spec/feature/1")
    run.record("feature")
    stale = run.records["feature"]["hash"]
    run.write("feature", RETAGGED)
    return stale


def test_a_changed_tier_is_reported_with_the_way_out_and_not_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    stale = failed_unit_with_retagged_group(run)
    before = run.store.get("feature/1")

    code, out = run.run(capsys, "feature")

    assert code == 1
    assert run.calls == 0
    assert "feature/1" in out
    assert "tier2" in out
    assert "abk requeue --restart feature/1" in out
    assert run.store.get("feature/1") == before
    assert run.records["feature"]["hash"] == stale


def test_the_report_repeats_until_the_tag_is_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    stale = failed_unit_with_retagged_group(run)

    first = cli.plan_all(run.inst, store=run.store)
    second = cli.plan_all(run.inst, store=run.store)
    run.write("feature", tasks_md(1))
    restored = cli.plan_all(run.inst, store=run.store)

    assert first["feature"].status != "planned"
    assert second["feature"].status != "planned"
    assert run.calls == 0
    assert restored["feature"].status in ("planned", "skipped")
    assert run.records["feature"]["hash"] == stale


def test_a_unit_requeued_with_restart_takes_the_new_tags_and_the_report_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    failed_unit_with_retagged_group(run)
    cli.plan_all(run.inst, store=run.store)
    assert run.calls == 0

    cli.requeue(run.inst, "feature/1", "restart", say=lambda text, error=False: None)
    retagged = dict(planned("feature/1", (1,)), tier="tier2")
    code, out = run.run(capsys, "feature", reply=answer(retagged))

    assert code == 0, out
    assert run.store.get("feature/1").tier == "tier2"
    assert run.records["feature"]["ok"] is True
