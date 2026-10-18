"""A tag edited under a started unit is reported, never applied, and never recorded as done."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import FAILED, MERGED, Member
from tests.cli.replan_driver import Replan, answer, planned, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

RETAGGED = tasks_md(1).replace("[unit-test]", "[e2e-test]")


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
    assert "with tier 'unit-test' but its group 1 is now 'e2e-test'" in out
    assert "TestTier" not in out
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
    retagged = dict(planned("retagged", (1,)), change="feature", tier="e2e-test")
    code, out = run.run(capsys, "feature", reply=answer(retagged))

    assert code == 0, out
    assert run.store.get("feature/1").tier == "e2e-test"
    assert run.records["feature"]["ok"] is True


def test_a_started_unit_stored_before_flags_were_kept_is_not_reported_for_its_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flagged = tasks_md(1).replace("[unit-test]", "[unit-test] [narrow]")
    run = Replan(tmp_path, monkeypatch, feature=flagged)
    run.store.upsert([unit("feature/1", change="feature", groups=(1,))])
    run.store.set_state("feature/1", FAILED, branch="spec/feature/1")
    run.record("feature")
    run.write("feature", flagged.replace("Group 1", "Group 1, reworded"))

    results = cli.plan_all(run.inst, store=run.store)

    assert run.calls == 0
    assert results["feature"].status == "planned"
    assert run.records["feature"]["ok"] is True


def test_a_merged_units_report_offers_only_restoring_the_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    run.store.upsert([unit("feature/1", change="feature", groups=(1,))])
    run.store.set_state("feature/1", MERGED, branch="spec/feature/1")
    run.record("feature")
    run.write("feature", RETAGGED)

    _, out = run.run(capsys, "feature")

    assert "feature/1" in out
    assert "restore the tag" in out
    assert "requeue" not in out


def test_a_retagged_second_group_of_a_started_unit_is_reported_by_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2))
    run.store.upsert([unit("feature/1", change="feature", groups=(1, 2))])
    run.store.set_state("feature/1", FAILED, branch="spec/feature/1")
    run.record("feature")
    stale = run.records["feature"]["hash"]
    run.write("feature", tasks_md(2).replace("[unit-test] Group 2", "[e2e-test] Group 2"))
    capsys.readouterr()

    results = cli.plan_all(run.inst, store=run.store)

    assert results["feature"].status == "refused"
    assert "its group 2" in capsys.readouterr().out
    assert run.calls == 0
    assert run.records["feature"]["hash"] == stale


def test_a_retagged_group_a_started_unit_of_another_change_carries_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1), base=tasks_md(1))
    joined = (Member(change="feature", groups=(1,)),)
    run.store.upsert([unit("base/1", change="base", groups=(1,), joined=joined)])
    run.store.set_state("base/1", FAILED, branch="spec/base/1")
    run.record("feature")
    stale = run.records["feature"]["hash"]
    run.write("feature", RETAGGED)
    capsys.readouterr()

    results = cli.plan_all(run.inst, store=run.store, only={"feature"})

    assert results["feature"].status == "refused"
    assert "base/1" in capsys.readouterr().out
    assert run.calls == 0
    assert run.records["feature"]["hash"] == stale
