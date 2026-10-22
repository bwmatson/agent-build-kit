"""A `Needs:` line is only a dependency: the dependent starts on the parent's branch.

The scenarios that ask what a dependent waits for write a plain line: the word `merged`
after the group number is a merge dependency (see the merge-need tests), so a plain line
is the one that starts on the parent's branch.
The lines go through `link_needs`, as every tick applies them, and the scheduling
questions are asked of the units it leaves in the store.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    UnitState,
    base_of,
    branch_name,
    ready_units,
    waiting_on,
)
from tests.cli.replan_driver import OPT_OUT, Replan, tasks_md
from tests.factories import unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

SLOTS = {"max_concurrent": 5, "depth_cap": 5}


def needing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *lines: str, **units: UnitState
) -> Replan:
    """A change `feature` whose one group carries `lines` as `Needs:` lines, a unit for
    it, and a unit of each other change named in `units`, in that state. A change named
    `shared` lives in the `platform` repository."""
    text = f"# Tasks\n\n{OPT_OUT}\n## 1. [app] [unit-test] The work\n\n"
    text += "".join(f"Needs: {line} — a reason\n" for line in lines)
    text += "\n- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n"
    run = Replan(tmp_path, monkeypatch, feature=text)
    run.store.upsert([unit("feature/1", change="feature", groups=(1,))])
    for change, state in units.items():
        repo = "platform" if change == "shared" else "app"
        run.store.upsert([unit(f"{change}/1", change=change, groups=(1,), repo=repo)])
        run.store.set_state(f"{change}/1", state, branch=f"spec/{change}/1", pr=4)
    return run


def link(run: Replan):
    cli.link_needs(run.inst, store=run.store)
    return run.store.get("feature/1"), run.store.all()


def test_a_same_repo_parent_in_review_releases_the_dependent_onto_its_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = needing(tmp_path, monkeypatch, "base group 1", base=IN_REVIEW)

    dependent, graph = link(run)

    assert waiting_on(dependent, graph) == []
    assert dependent in ready_units(graph, **SLOTS)
    assert base_of(dependent, graph) == branch_name(run.store.get("base/1"))


@pytest.mark.parametrize("state", [PLANNED, RUNNING, FAILED, HELD])
def test_a_same_repo_parent_still_building_keeps_the_dependent_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: UnitState
) -> None:
    run = needing(tmp_path, monkeypatch, "base group 1", base=IN_REVIEW)
    run.store.set_state("base/1", state, branch="spec/base/1")

    dependent, graph = link(run)
    assert [parent.id for parent in waiting_on(dependent, graph)] == ["base/1"]

    # It is the line that released it a moment ago, not the parent's state alone.
    run.store.set_state("base/1", IN_REVIEW, pr=4)
    assert waiting_on(*link(run)) == []


def test_a_parent_sent_back_for_rework_pauses_the_dependent_until_it_is_back_in_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = needing(tmp_path, monkeypatch, "base group 1", base=IN_REVIEW)
    run.store.set_state("base/1", PLANNED, pr=4)
    run.store.set_feedback("base/1", "use a Sequence")

    dependent, graph = link(run)
    assert [parent.id for parent in waiting_on(dependent, graph)] == ["base/1"]
    assert dependent not in ready_units(graph, **SLOTS)

    run.store.set_state("base/1", IN_REVIEW, pr=4)
    dependent, graph = link(run)
    assert waiting_on(dependent, graph) == []
    assert dependent in ready_units(graph, **SLOTS)


def test_a_cross_repo_parent_still_has_to_merge_and_a_same_repo_one_in_review_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = needing(
        tmp_path,
        monkeypatch,
        "base group 1",
        "shared group 1",
        base=IN_REVIEW,
        shared=IN_REVIEW,
    )

    dependent, graph = link(run)
    assert [parent.id for parent in waiting_on(dependent, graph)] == ["shared/1"]
    assert base_of(dependent, graph) == branch_name(run.store.get("base/1"))

    run.store.set_state("shared/1", MERGED, pr=4)
    assert waiting_on(*link(run)) == []

    run.store.set_state("shared/1", SATISFIED)
    assert waiting_on(*link(run)) == [], "satisfied with nothing left to land"


def test_an_edit_that_changes_only_a_needs_line_asks_the_planner_nothing_and_applies_next_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Replan(tmp_path, monkeypatch, base=tasks_md(1), feature=tasks_md(1))
    run.store.upsert(
        [
            unit("base/1", change="base", groups=(1,)),
            unit("feature/1", change="feature", groups=(1,)),
        ]
    )
    run.store.set_state("base/1", IN_REVIEW, branch="spec/base/1", pr=4)
    run.record("base")
    run.record("feature")

    run.write("feature", tasks_md(1, needs={1: "base group 1"}))
    cli.plan_all(run.inst, store=run.store)

    assert run.calls == 0
    dependent, graph = link(run)
    assert dependent.depends_on == ("base/1",)
    assert waiting_on(dependent, graph) == []
    assert base_of(dependent, graph) == branch_name(run.store.get("base/1"))


def test_a_stored_merge_gate_no_longer_holds_a_unit_whose_parent_is_in_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = needing(tmp_path, monkeypatch, "base group 1", base=IN_REVIEW)
    run.store.set_dependencies("feature/1", ("base/1",))
    # What an earlier version left in the store: the key is written beside the record.
    path = run.inst.state_dir / "units.json"
    raw = json.loads(path.read_text())
    records = raw["units"].values() if isinstance(raw["units"], dict) else raw["units"]
    for record in records:
        if record["id"] == "feature/1":
            record["merge_before"] = ["base/1"]
    path.write_text(json.dumps(raw))

    dependent, graph = link(run)

    assert waiting_on(dependent, graph) == []
    assert dependent in ready_units(graph, **SLOTS)
    assert base_of(dependent, graph) == branch_name(run.store.get("base/1"))


# --- the warning ----------------------------------------------------------------


def two_merged_lines(run: Replan) -> None:
    run.write(
        "feature",
        f"# Tasks\n\n{OPT_OUT}\n"
        "## 1. [app] [unit-test] One\n\n- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n\n"
        "## 2. [app] [unit-test] Two\n\nNeeds: base group 1 merged — they edit one file\n"
        "Needs: other group 1 — it adds the field\n\n- [ ] 2.1 Test: it.\n- [ ] 2.2 Do it.\n\n"
        "## 3. [app] [unit-test] Three\n\nNeeds: base group 1 merged\n\n"
        "- [ ] 3.1 Test: it.\n- [ ] 3.2 Do it.\n",
    )


def warnings_in(capsys: pytest.CaptureFixture[str]) -> list[str]:
    seen = capsys.readouterr()
    return [line for line in (seen.out + seen.err).splitlines() if "deprecated" in line]


def test_abk_tags_does_not_warn_of_a_merged_needs_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    two_merged_lines(run)

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), run.inst)

    warned = warnings_in(capsys)
    assert status == 0
    assert warned == []


def test_abk_check_does_not_warn_of_a_merged_needs_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    two_merged_lines(run)
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    status = cli.cmd_check(argparse.Namespace(), run.inst)

    warned = warnings_in(capsys)
    assert status == 0
    assert warned == []


def test_merged_on_the_changes_own_group_is_an_error_and_another_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(1))
    run.write(
        "feature",
        f"# Tasks\n\n{OPT_OUT}\n"
        "## 1. [app] [unit-test] One\n\n- [ ] 1.1 Test: it.\n- [ ] 1.2 Do it.\n\n"
        "## 2. [app] [unit-test] Two\n\nNeeds: feature group 1 merged — why\n"
        "Needs: base group 1 merged — they edit one file\n\n"
        "- [ ] 2.1 Test: it.\n- [ ] 2.2 Do it.\n",
    )

    status = cli.cmd_tags(argparse.Namespace(change="feature", all=False), run.inst)

    seen = capsys.readouterr()
    assert status == 1
    assert "own group" in seen.out + seen.err
    assert "deprecated" not in seen.out + seen.err
