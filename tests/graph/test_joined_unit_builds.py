"""A unit that carries task groups from more than one change, built on the graph.

The build and review prompts name every change the unit carries, the scope note
treats carried groups as the unit's own, each change's groups are ticked in its
own tasks file when the unit is done, and a failed unit unticks every change.
The unit is joined by hand: nothing here produces one by planning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Member
from tests.factories import stored_unit
from tests.graph_driver import run_on_graph
from tests.runner_fakes import Recorder, make_runner

CARRIED = Member(change="sample-change", groups=(7, 8))


def carrying(**overrides: Any) -> StoredUnit:
    """A unit of add-marker that also carries groups 7 and 8 of sample-change."""
    return stored_unit(joined=(CARRIED,), **overrides)


def build_joined(
    tmp_path: Path,
    joined: StoredUnit,
    *,
    graph: list[StoredUnit] | None = None,
    **options: Any,
) -> tuple[Recorder, RunOutcome]:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([joined, *(graph or [])])
    recorder = Recorder(store, **options)
    runner = make_runner(store, recorder, tmp_path)
    return recorder, run_on_graph(runner, store.get(joined.id), graph=graph)


def tasks(tmp_path: Path, change: str, groups: tuple[int, ...]) -> Path:
    path = tmp_path / "meta" / "openspec" / "changes" / change / "tasks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            f"## {g}. [app] [tier1] G{g}\n- [ ] {g}.1 Test: a\n- [ ] {g}.2 Do a\n" for g in groups
        )
    )
    return path


def ticked(path: Path) -> set[int]:
    return {
        int(line.split()[2].split(".")[0])
        for line in path.read_text().splitlines()
        if line.startswith("- [x]")
    }


def test_the_build_and_review_prompts_name_every_change_and_its_groups(tmp_path: Path) -> None:
    recorder, outcome = build_joined(tmp_path, carrying(groups=(1, 2)))

    assert outcome.status == "open"
    assert len(recorder.prompts) == 2, "the tests and the implementation"
    for prompt in recorder.prompts:
        assert "openspec/changes/add-marker" in prompt
        assert "openspec/changes/sample-change" in prompt
        assert "1, 2" in prompt
        assert "7, 8" in prompt
    assert any(
        "add-marker" in context and "sample-change" in context and "7, 8" in context
        for context in recorder.contexts
    ), "the reviewer is told what the unit carries, even with no later unit"


def test_a_rework_prompt_names_every_change_too(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([carrying(groups=(1, 2))])
    store.set_feedback("add-marker/1", "rename it")
    recorder = Recorder(store)

    run_on_graph(make_runner(store, recorder, tmp_path), store.get("add-marker/1"))

    assert recorder.events.count("claude:rework") == 1
    (prompt,) = recorder.prompts
    assert "openspec/changes/add-marker" in prompt
    assert "openspec/changes/sample-change" in prompt
    assert "7, 8" in prompt


def test_the_scope_note_treats_carried_groups_as_this_units_own(tmp_path: Path) -> None:
    """Groups 4 and 5 of sample-change are carried, so they are not later work;
    group 6 of the same change, in another unit, still is."""
    carried = Member(change="sample-change", groups=(4, 5))
    later = stored_unit("sample-change/2", change="sample-change", groups=(6,))

    recorder, _ = build_joined(
        tmp_path,
        stored_unit(groups=(1,), joined=(carried,)),
        graph=[stored_unit(groups=(1,), joined=(carried,)), later],
    )

    notes = [
        line
        for text in (*recorder.prompts, *recorder.contexts)
        for line in text.splitlines()
        if "belong to later" in line
    ]
    assert notes, "the later group is still fenced off"
    for line in notes:
        assert "6" in line
        assert "4" not in line
        assert "5" not in line


def test_each_changes_groups_are_ticked_in_its_own_tasks_file(tmp_path: Path) -> None:
    mine = tasks(tmp_path, "add-marker", (1, 2, 3))
    theirs = tasks(tmp_path, "sample-change", (6, 7, 8, 9))

    _, outcome = build_joined(tmp_path, carrying(groups=(2,)))

    assert outcome.status == "open"
    assert ticked(mine) == {2}
    assert ticked(theirs) == {7, 8}


def test_a_satisfied_joined_unit_ticks_every_change_it_carries(tmp_path: Path) -> None:
    mine = tasks(tmp_path, "add-marker", (2,))
    theirs = tasks(tmp_path, "sample-change", (7, 8))
    store = UnitStore(tmp_path / "units.json")
    store.upsert([carrying(groups=(2,))])
    recorder = Recorder(store, commits_from_impl=0)
    runner = make_runner(store, recorder, tmp_path, branch_commits=lambda cwd, base: 0)

    outcome = run_on_graph(runner, store.get("add-marker/1"))

    assert outcome.status == "satisfied"
    assert ticked(mine) == {2}
    assert ticked(theirs) == {7, 8}


def test_a_failed_joined_unit_unticks_every_change_it_carries(tmp_path: Path) -> None:
    mine = tasks(tmp_path, "add-marker", (2,))
    theirs = tasks(tmp_path, "sample-change", (7, 8))
    for path in (mine, theirs):
        path.write_text(path.read_text().replace("- [ ]", "- [x]"))  # a build agent's doing

    _, outcome = build_joined(tmp_path, carrying(groups=(2,)), tier1_ok=False)

    assert outcome.status == "failed"
    assert ticked(mine) == set()
    assert ticked(theirs) == set()
