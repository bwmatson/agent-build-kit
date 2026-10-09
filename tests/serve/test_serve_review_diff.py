"""A unit's review diff is its own work against the base the pipeline builds it
on, pinned to one resolved commit (spec: ui-review)."""

from __future__ import annotations

import re

import httpx

from agent_build_kit.installation import Installation
from tests.factories import git
from tests.review_repo import TWO, advance, rev, seed_branches
from tests.serving import seed_pipeline


def files_in(patch: str) -> list[str]:
    return re.findall(r"^diff --git a/\S+ b/(\S+)$", patch, flags=re.MULTILINE)


def test_a_plain_unit_is_diffed_against_the_trunk_as_it_forked_from_it(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    advance(repo, "main", "later.txt", "main moved on\n")

    answer = api.get("/api/units/feature/2/diff")

    assert answer.status_code == 200
    body = answer.json()
    assert body["base"] == "main"
    assert files_in(body["patch"]) == ["two.py"]
    assert "+two line 1" in body["patch"]


def test_a_stacked_unit_shows_only_its_own_work_against_the_branch_it_stacks_on(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)

    body = api.get("/api/units/feature/4/diff").json()

    assert body["base"] == "spec/feature/2"
    assert files_in(body["patch"]) == ["four.py"]


def test_a_restacked_unit_shows_only_its_own_work_over_the_rewritten_base(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    old_base = rev(repo, "spec/feature/2")
    # The predecessor is amended, then the unit is moved onto the new head.
    git(repo, "checkout", "-q", "spec/feature/2")
    (repo / "two.py").write_text(TWO + "amended\n")
    git(repo, "commit", "-q", "-a", "--amend", "--no-edit")
    git(repo, "rebase", "-q", "--onto", "spec/feature/2", old_base, "spec/feature/4")
    git(repo, "checkout", "-q", "main")

    body = api.get("/api/units/feature/4/diff").json()

    assert body["base_commit"] == rev(repo, "spec/feature/2")
    assert files_in(body["patch"]) == ["four.py"]


def test_the_diff_names_the_one_commit_it_was_taken_at(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    repo = seed_branches(inst)
    pinned = rev(repo, "spec/feature/2")

    first = api.get("/api/units/feature/2/diff").json()
    moved = advance(repo, "spec/feature/2", "extra.py", "extra\n")
    latest = api.get("/api/units/feature/2/diff").json()
    earlier = api.get("/api/units/feature/2/diff", params={"commit": pinned}).json()

    assert first["commit"] == pinned
    assert latest["commit"] == moved
    assert files_in(latest["patch"]) == ["extra.py", "two.py"]
    # Asking for the pinned commit again gives the diff as it was.
    assert earlier["commit"] == pinned
    assert earlier["patch"] == first["patch"]


def test_a_unit_with_no_branch_has_nothing_to_diff_and_says_so(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)
    seed_branches(inst)

    answer = api.get("/api/units/feature/8/diff")

    assert answer.status_code == 409
    assert "branch" in answer.json()["detail"]
