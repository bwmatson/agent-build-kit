"""The planner is shown the units that can affect a plan, and one line for the landed units of
other changes (spec: planner-in-flight)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    RUNNING,
    SATISFIED,
    UnitState,
)
from tests.cli.replan_driver import Replan, answer, needs_md, planned, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

OLD = "a-change-whose-units-all-merged-long-ago"
QUEUED = "a-change-whose-units-are-still-planned"
SUMMARY = "4 merged or satisfied units of other changes are in the trunk and omitted"


def add(run: Replan, uid: str, state: UnitState | None = None, **fields) -> None:
    fields = {"groups": (1,), **fields}
    run.store.upsert([unit(uid, change=uid.split("/")[0], **fields)])
    if state is not None:
        run.store.set_state(uid, state, branch=f"spec/{uid}", pr=1)


def landed_and_open(run: Replan) -> None:
    for uid in ("old/1", "old/2", "old/3"):
        add(run, uid, MERGED)
    add(run, "sat/1", SATISFIED)
    add(run, "bad/1", FAILED)
    add(run, "hold/1", HELD)
    add(run, "rev/1", IN_REVIEW)
    add(run, "plan/1")
    add(run, "plan/2")


def test_landed_units_of_other_changes_become_one_line_and_the_rest_stay_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(4))
    for name in ("old", "sat", "bad", "hold", "rev", "plan"):
        run.write(name, tasks_md(1))
    landed_and_open(run)
    add(run, "feature/1", MERGED, groups=(1,))
    add(run, "feature/2", MERGED, groups=(2,))
    add(run, "feature/3", RUNNING, groups=(3,))
    run.runtime.answer = answer(planned("feature/4", (4,)))

    cli.plan_all(run.inst, store=run.store, only={"feature"})

    prompt = run.runtime.request.prompt
    lines = prompt.splitlines()
    for listed in ("feature/1", "feature/2", "feature/3", "bad/1", "hold/1", "rev/1", "plan/1"):
        assert any(line.startswith(f"- {listed} ") for line in lines), listed
    assert any(line.startswith("- plan/2 ") for line in lines)
    for landed in ("old/1", "old/2", "old/3", "sat/1"):
        assert not any(line.startswith(f"- {landed} ") for line in lines), landed
    assert SUMMARY in lines
    assert "## 1. [app] [tier1] Group 1 (built by feature/1)" in lines


def test_the_line_appears_only_when_a_unit_of_another_change_has_landed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(2), bad=tasks_md(1), old=tasks_md(1))
    add(run, "bad/1", FAILED)
    add(run, "feature/1", MERGED)
    run.runtime.answer = answer(planned("feature/2", (2,)))

    cli.plan_all(run.inst, store=run.store, only={"feature"})

    prompt = run.runtime.request.prompt
    assert "- bad/1 " in prompt
    assert "- feature/1 " in prompt
    assert "of other changes are in the trunk and omitted" not in prompt

    add(run, "old/1", MERGED)
    cli.plan_all(run.inst, store=run.store, only={"feature"}, force=True)

    assert re.search(
        r"1 merged or satisfied units? of other changes are in the trunk and omitted",
        run.runtime.requests[-1].prompt,
    )


def omitted_feature(run: Replan, reply: str) -> tuple[str, str]:
    """`feature` planned with `old/1` merged and omitted: the prompt, and the plan's status."""
    add(run, "old/1", MERGED)
    run.runtime.answer = reply
    results = cli.plan_all(run.inst, store=run.store, only={"feature"})
    return run.runtime.request.prompt, results["feature"].status


def test_a_plan_that_depends_on_an_omitted_unit_passes_the_plan_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=needs_md("old group 1"), old=tasks_md(1))

    prompt, status = omitted_feature(run, answer(planned("feature/1", (1,), depends_on=("old/1",))))

    assert re.search(r"1 merged or satisfied units? of other changes are in the trunk", prompt)
    assert "- old/1 " not in prompt
    assert status == "planned"


def test_a_needs_line_naming_a_group_an_omitted_unit_built_still_yields_its_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=needs_md("old group 1"), old=tasks_md(1))

    prompt, status = omitted_feature(run, answer(planned("feature/1", (1,))))
    cli.link_needs(run.inst, store=run.store)

    assert re.search(r"1 merged or satisfied units? of other changes are in the trunk", prompt)
    assert "- old/1 " not in prompt
    assert status == "planned"
    assert "old/1" in run.store.get("feature/1").depends_on


def test_a_store_of_hundreds_of_landed_and_planned_units_gives_a_prompt_under_100_kb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    padding = "".join(f"- [ ] 1.{n} Do: {'x' * 70}\n" for n in range(3, 500))
    assert 38_000 <= len(padding) <= 45_000
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1) + padding)
    for name in (OLD, QUEUED, "misc"):
        run.write(name, tasks_md(1))
    run.store.upsert(
        [
            *(unit(f"{OLD}/{n}", change=OLD, groups=(n,)) for n in range(1, 361)),
            *(unit(f"{QUEUED}/{n}", change=QUEUED, groups=(n,)) for n in range(1, 141)),
            *(unit(f"misc/{n}", change="misc", groups=(n,)) for n in range(1, 13)),
        ]
    )
    for n in range(1, 361):
        run.store.set_state(f"{OLD}/{n}", MERGED, branch=f"spec/{OLD}/{n}", pr=n)
    for n in range(1, 13):
        run.store.set_state(f"misc/{n}", FAILED, branch=f"spec/misc/{n}", pr=n)
    run.runtime.answer = answer(planned("feature/1", (1,)))

    cli.plan_all(run.inst, store=run.store, only={"feature"})

    assert len(run.runtime.request.prompt.encode()) < 100_000
