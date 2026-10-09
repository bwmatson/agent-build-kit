"""The review answer carries the reviewer's findings and follow-ups, and an address made
at an earlier commit is relocated to the branch tip (spec: ui-review)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import Node, UnitRun
from agent_build_kit.graph.unit import seed_thread
from agent_build_kit.installation import Installation
from tests.factories import git
from tests.review_repo import TWO, commit, rev, seed_branches
from tests.serving import seed_pipeline

LOCATE = "/api/units/feature/2/review/locate"


def seed_run(inst: Installation, **fields: Any) -> None:
    state = UnitRun(unit_id="feature/2", change="feature", **fields)

    async def write() -> None:
        async with open_checkpointer(unit_graphs_path(inst.state_dir)) as saver:
            await seed_thread(saver, state, as_node=Node.AWAIT_REVIEW)

    asyncio.run(write())


def test_the_review_lists_the_latest_rounds_findings_and_the_deferred_follow_ups(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)
    first = {"id": "1.1", "file": "two.py", "line": 2, "summary": "old", "required": True}
    latest = {
        "id": "2.1",
        "file": "two.py",
        "line": 3,
        "summary": "no test",
        "consequence": "a regression goes unseen",
        "done": "add one",
        "required": True,
        "status": "",
    }
    unplaced = {"id": "2.2", "file": "two.py", "line": None, "summary": "docstring"}
    seed_run(
        inst,
        review_round=2,
        # Mid-review the rounds are kept; the last round's findings are the latest one's.
        review_rounds=({"findings": [first]}, {"findings": [latest, unplaced]}),
        last_findings=(latest, unplaced),
        deferred=("Add a changelog entry",),
    )

    answer = api.get("/api/units/feature/2/review").json()

    assert answer["findings"] == [
        {"id": "2.1", "file": "two.py", "line": 3, "summary": "no test", "required": True},
        {"id": "2.2", "file": "two.py", "line": None, "summary": "docstring", "required": False},
    ]
    assert answer["follow_ups"] == ["Add a changelog entry"]
    assert answer["round"] == 2


def test_a_pushed_units_review_lists_the_last_rounds_findings_and_the_deferred_follow_ups(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)
    latest = {"id": "2.1", "file": "two.py", "line": 3, "summary": "no test", "required": True}
    seed_run(
        inst,
        review_round=2,
        # What a pushed unit holds: the rounds are cleared, the last round's findings kept.
        review_rounds=(),
        last_findings=(latest,),
        deferred=("Add a changelog entry",),
    )

    answer = api.get("/api/units/feature/2/review").json()

    assert [f["id"] for f in answer["findings"]] == ["2.1"]
    assert answer["follow_ups"] == ["Add a changelog entry"]


def test_the_follow_ups_are_this_units_block_of_the_changes_file_once_the_push_cleared_deferred(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)
    change_dir = inst.root / "openspec" / "changes" / "feature"
    change_dir.mkdir(parents=True)
    (change_dir / "follow-ups.md").write_text(
        "## From `feature/1`\n\n- Belongs to unit one\n\n"
        "## From `feature/2`\n\n- Add a changelog entry\n- Tidy the helper\n\n"
    )
    seed_run(inst, review_round=1, deferred=("Tidy the helper", "Not yet pushed"))

    answer = api.get("/api/units/feature/2/review").json()

    assert answer["follow_ups"] == ["Add a changelog entry", "Tidy the helper", "Not yet pushed"]


def test_a_unit_with_no_block_in_the_follow_ups_file_has_none(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)
    change_dir = inst.root / "openspec" / "changes" / "feature"
    change_dir.mkdir(parents=True)
    (change_dir / "follow-ups.md").write_text("## From `feature/1`\n\n- Belongs to unit one\n\n")

    assert api.get("/api/units/feature/2/review").json()["follow_ups"] == []


def test_a_review_with_no_run_has_no_findings_or_follow_ups(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)

    answer = api.get("/api/units/feature/2/review").json()

    assert (answer["findings"], answer["follow_ups"]) == ([], [])


def test_a_line_that_still_matches_is_located_at_its_new_number(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    then = rev(repo, "spec/feature/2")
    git(repo, "checkout", "-q", "spec/feature/2")
    commit(repo, "two.py", "added\nadded\n" + TWO, "prepend")
    git(repo, "checkout", "-q", "main")

    answer = api.get(LOCATE, params={"file": "two.py", "line": 3, "commit": then})

    assert answer.json() == {"line": 5}


def test_a_line_that_was_deleted_is_located_nowhere(inst: Installation, api: httpx.Client) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    then = rev(repo, "spec/feature/2")
    git(repo, "checkout", "-q", "spec/feature/2")
    commit(repo, "two.py", TWO.replace("two line 3\n", ""), "drop")
    git(repo, "checkout", "-q", "main")

    answer = api.get(LOCATE, params={"file": "two.py", "line": 3, "commit": then})

    assert answer.json() == {"line": None}


def test_an_old_side_line_stays_where_it_is(inst: Installation, api: httpx.Client) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    then = rev(repo, "spec/feature/2")

    answer = api.get(LOCATE, params={"file": "base.txt", "line": 1, "side": "old", "commit": then})

    assert answer.json() == {"line": 1}


def test_a_branch_that_is_not_in_the_checkout_is_named_as_the_problem(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    then = rev(repo, "spec/feature/2")
    git(repo, "branch", "-q", "-D", "spec/feature/2", "spec/feature/4")

    answer = api.get(LOCATE, params={"file": "two.py", "line": 1, "commit": then})

    assert answer.status_code == 409
    assert "branch" in answer.json()["detail"]


def test_a_commit_that_is_not_in_the_checkout_is_refused(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)

    answer = api.get(LOCATE, params={"file": "two.py", "line": 1, "commit": "deadbeef"})

    assert answer.status_code == 409
