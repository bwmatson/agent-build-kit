"""A started unit's stored kind is compared with the widest kind of the groups it carries."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import FAILED, Member
from tests.cli.replan_driver import Replan, tagged_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")


def started_unit_of(run: Replan) -> None:
    run.store.upsert([unit("feature/1", change="feature", tier="integration-test", groups=(1, 2))])
    run.store.set_state("feature/1", FAILED, branch="spec/feature/1")
    run.record("feature")


def test_a_unit_agrees_with_the_widest_kind_of_its_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tagged_md("unit-test", "integration-test"))
    started_unit_of(run)
    run.write("feature", tagged_md("unit-test", "integration-test").replace("Group 1", "Group one"))
    capsys.readouterr()

    results = cli.plan_all(run.inst, store=run.store)

    assert results["feature"].status != "refused"
    assert "feature/1" not in capsys.readouterr().out


def test_retagging_the_wider_group_reports_a_difference_naming_the_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tagged_md("unit-test", "integration-test"))
    started_unit_of(run)
    run.write("feature", tagged_md("unit-test", "unit-test"))
    capsys.readouterr()

    results = cli.plan_all(run.inst, store=run.store)

    assert results["feature"].status == "refused"
    assert "feature/1" in capsys.readouterr().out


def joined_unit_of(run: Replan) -> None:
    """A started `integration-test` unit of `base`: its own `unit-test` group, and `feature`'s
    `integration-test` group joined onto it."""
    joined = (Member(change="feature", groups=(1,)),)
    run.store.upsert(
        [unit("base/1", change="base", tier="integration-test", groups=(1,), joined=joined)]
    )
    run.store.set_state("base/1", FAILED, branch="spec/base/1")
    run.record("base")
    run.record("feature")


def test_a_unit_widened_by_a_joined_group_agrees_with_its_groups_across_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(
        tmp_path, monkeypatch, base=tagged_md("unit-test"), feature=tagged_md("integration-test")
    )
    joined_unit_of(run)
    run.write("base", tagged_md("unit-test").replace("Group 1", "Group one"))
    capsys.readouterr()

    results = cli.plan_all(run.inst, store=run.store, only={"base"})

    assert results["base"].status != "refused"
    assert "base/1" not in capsys.readouterr().out


def test_retagging_the_joined_group_narrows_the_unit_and_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(
        tmp_path, monkeypatch, base=tagged_md("unit-test"), feature=tagged_md("integration-test")
    )
    joined_unit_of(run)
    run.write("feature", tagged_md("unit-test"))
    capsys.readouterr()

    results = cli.plan_all(run.inst, store=run.store, only={"feature"})

    assert results["feature"].status == "refused"
    assert "base/1" in capsys.readouterr().out
