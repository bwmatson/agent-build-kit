"""A plan is stale when it was made under other ceilings or another `review:` section, or before
there was a review policy, and the reason says which; a stale plan is never work for a tick
(plan-migration: a plan made under other ceilings or another review policy is stale)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import dump
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.cli.replan_driver import (
    Replan,
    answer,
    enable_review,
    listing,
    planned,
    tasks_md,
    tick,
    ticking_replan,
)
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

PLAN = answer(planned("alpha/1", (1,)))
BEFORE_POLICY = "planned before the review policy"


def planned_under_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Replan:
    """A change planned for real under `ceilings.full: 750`, so its record carries that policy."""
    run = Replan(tmp_path, monkeypatch, alpha=tasks_md(1))
    enable_review(run, ceilings={"full": 750})
    code, _ = run.run(capsys, "alpha", reply=PLAN)
    assert code == 0
    return run


def test_a_plan_under_the_policy_in_force_is_current_until_the_ceilings_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planned_under_policy(tmp_path, monkeypatch, capsys)
    assert "stale" not in listing(run, capsys)["alpha"]

    enable_review(run, ceilings={"full": 900})

    line = listing(run, capsys)["alpha"]
    assert "stale" in line
    assert "ceilings changed" in line
    assert "review section" not in line


def test_a_changed_review_section_is_named_as_the_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planned_under_policy(tmp_path, monkeypatch, capsys)

    enable_review(run, ceilings={"full": 750}, protected_paths=["secrets/**"])

    line = listing(run, capsys)["alpha"]
    assert "stale" in line
    assert "review section changed" in line
    assert "ceilings changed" not in line


def digest_before_protected_config() -> str:
    """The sizing digest as it was computed before `protected_config` existed: the ceilings
    part as now, then the rest of the `review` blocks dumped without that field."""
    workspace = config.active()
    exclude = {"ceilings", "protected_config"}
    rest = {
        "review": workspace.review.model_dump(mode="json", exclude=exclude),
        "repos": {
            name: repo.review.model_dump(mode="json", exclude=exclude)
            for name, repo in workspace.repos.items()
        },
    }
    rest_part = hashlib.sha256(json.dumps(rest, sort_keys=True).encode()).hexdigest()
    return f"{cli.sizing_digest().split('.')[0]}.{rest_part}"


def set_protected_config(run: Replan, where: str) -> None:
    """Give the workspace, or each repo, a `protected_config` entry, in the active configuration
    and in the `abk.yaml` a command loads."""
    entry = {"**/pyproject.toml": ["tool.mypy"]}
    current = config.active()
    if where == "workspace":
        updated = current.model_copy(
            update={"review": current.review.model_copy(update={"protected_config": entry})}
        )
    else:
        repos = {
            name: repo.model_copy(
                update={"review": repo.review.model_copy(update={"protected_config": entry})}
            )
            for name, repo in current.repos.items()
        }
        updated = current.model_copy(update={"repos": repos})
    config.activate(updated, config.active_root())
    (run.inst.root / "abk.yaml").write_text(dump(updated))


@pytest.mark.parametrize("where", ["workspace", "repo"])
def test_a_plan_recorded_before_protected_config_stays_current_until_one_is_set(
    where: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, alpha=tasks_md(1))
    enable_review(run, ceilings={"full": 750})
    run.record("alpha", sizing=digest_before_protected_config())

    assert "stale" not in listing(run, capsys)["alpha"]

    set_protected_config(run, where)

    line = listing(run, capsys)["alpha"]
    assert "stale" in line
    assert "review section changed" in line


def test_a_plan_with_no_policy_digest_is_stale_for_want_of_one_and_is_not_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, alpha=tasks_md(1))
    enable_review(run)
    run.record("alpha")

    assert BEFORE_POLICY in listing(run, capsys)["alpha"]
    assert not cli.has_work(run.inst, run.store), "a stale plan alone is no work"


def test_a_tick_over_three_stale_plans_makes_no_planner_call_and_logs_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    changes = ("alpha", "beta", "gamma")
    run = ticking_replan(
        tmp_path, monkeypatch, {change: tasks_md(1) for change in (*changes, "done")}
    )
    for change in changes:
        run.record(change)
        run.store.upsert([unit(f"{change}/1", change=change, groups=(1,))])
    run.record_finished("done")
    # Something else in progress makes the tick run, so what it says is heard.
    run.store.upsert([unit("other/1", change="other", groups=(1,))])
    run.store.set_state("other/1", IN_REVIEW, pr=5, branch="spec/other/1")

    code, out = tick(run, capsys)

    assert code == 0
    assert run.calls == 0
    for change in changes:
        lines = [line for line in out.splitlines() if change in line and BEFORE_POLICY in line]
        assert len(lines) == 1, f"{change} is logged once, with its reason:\n{out}"
    assert not [line for line in out.splitlines() if "done" in line and BEFORE_POLICY in line]
