"""Turning a change's task groups into units of work.

A unit is one PR's worth of work in one repo (docs/architecture.md).
Task groups are the raw material; these rules decide where the
boundaries fall, what each unit stacks on, and which ones may run now.

All of it is pure: given a graph, the answers are the same every time. The
planner that produces the graph is a separate concern, and the parts that
touch git and GitHub are separate again.
"""

import pytest

from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    RUNNING,
    base_of,
    branch_name,
    depth_of,
    plan_units,
    ready_units,
)
from tests.factories import unit


def group(number: int, repo: str = "app", tier: str = "tier1", lines: int = 200, **kw) -> dict:
    return {
        "number": number,
        "repo": repo,
        "tier": tier,
        "title": f"group {number}",
        "estimated_lines": lines,
        "fans_out": kw.get("fans_out", False),
    }


def test_small_consecutive_groups_become_one_unit() -> None:
    """The chain-of-tiny-PRs problem: three 200-line groups in a row are one
    PR's worth of work, not three."""
    units = plan_units("add-marker", [group(1), group(2), group(3)], min_lines=500)

    assert len(units) == 1
    assert units[0].estimated_lines == 600
    assert units[0].groups == (1, 2, 3)


def test_absorbing_stops_once_the_floor_is_reached() -> None:
    """A floor, not a target: it stops as soon as it's met rather than
    sweeping up everything that follows."""
    units = plan_units(
        "add-marker", [group(1, lines=300), group(2, lines=300), group(3)], min_lines=500
    )

    assert [u.groups for u in units] == [(1, 2), (3,)]


def test_a_group_bigger_than_the_floor_stands_alone() -> None:
    units = plan_units("add-marker", [group(1, lines=900), group(2)], min_lines=500)

    assert [u.groups for u in units] == [(1,), (2,)]


def test_a_fan_out_group_ends_its_unit_however_small() -> None:
    """Stopping early is worth it when finishing unblocks other work."""
    units = plan_units("add-marker", [group(1, lines=50, fans_out=True), group(2)], min_lines=500)

    assert [u.groups for u in units] == [(1,), (2,)]


def test_units_never_span_repos() -> None:
    """A branch lives in one repo, so a unit does too — even when both groups
    are tiny and would otherwise be absorbed."""
    units = plan_units(
        "add-marker",
        [group(1, repo="platform", lines=50), group(2, repo="app", lines=50)],
        min_lines=500,
    )

    assert [(u.repo, u.groups) for u in units] == [("platform", (1,)), ("app", (2,))]


def test_tiers_do_not_split_a_unit() -> None:
    """Test tier decides how a unit is verified, not what belongs together."""
    units = plan_units(
        "add-marker",
        [group(1, tier="tier1", lines=200), group(2, tier="tier2", lines=200)],
        min_lines=300,
    )

    assert len(units) == 1
    assert units[0].tier == "tier2", "a unit needing the stack anywhere needs it overall"


def test_units_depend_on_the_one_before_them_in_the_same_repo() -> None:
    units = plan_units(
        "add-marker",
        [group(1, lines=600), group(2, lines=600), group(3, repo="platform")],
        min_lines=500,
    )

    assert units[1].depends_on == (units[0].id,)
    assert units[2].depends_on == (units[1].id,), "cross-repo order is still order"


def test_branch_names_are_deterministic() -> None:
    """A re-run must reuse the branch and keep the work already on it, so the
    name can't carry a timestamp or a slug that drifts."""
    first = branch_name(unit("add-marker/2"))
    again = branch_name(unit("add-marker/2", title="renamed since"))

    assert first == again == "spec/add-marker/2"


def test_a_unit_with_no_open_dependency_starts_from_main() -> None:
    graph = [unit("a", state="merged"), unit("b", depends_on=("a",))]

    assert base_of(graph[1], graph) == "main"


def test_a_unit_stacks_on_its_newest_open_dependency() -> None:
    """Nothing starts from main by default: if the work it needs is in flight,
    it stacks on that branch rather than duplicating or conflicting with it."""
    graph = [
        unit("add-marker/1", state="in_review"),
        unit("add-marker/2", depends_on=("add-marker/1",)),
    ]

    assert base_of(graph[1], graph) == "spec/add-marker/1"


def test_a_cross_repo_dependency_is_never_a_base() -> None:
    """Stacks can't span repos, so that edge is an ordering constraint only —
    the dependent waits for a merge instead."""
    graph = [
        unit("a", repo="platform", state="in_review"),
        unit("b", repo="app", depends_on=("a",)),
    ]

    assert base_of(graph[1], graph) == "main"


def test_depth_counts_the_longest_chain_of_open_prs() -> None:
    graph = [
        unit("a", state="in_review"),
        unit("b", depends_on=("a",), state="in_review"),
        unit("c", depends_on=("b",), state="planned"),
    ]

    assert depth_of(graph[2], graph) == 3


def test_merged_ancestors_do_not_count_toward_depth() -> None:
    """Merging the bottom PR frees a layer for everything above it."""
    graph = [
        unit("a", state="merged"),
        unit("b", depends_on=("a",), state="in_review"),
        unit("c", depends_on=("b",), state="planned"),
    ]

    assert depth_of(graph[2], graph) == 2


def test_siblings_share_a_depth_rather_than_adding_to_it() -> None:
    """A stack is a tree: two units on one base both sit at depth 2, and each
    can still carry a child."""
    graph = [
        unit("a", state="in_review"),
        unit("b", depends_on=("a",), state="in_review"),
        unit("c", depends_on=("a",), state="in_review"),
    ]

    assert depth_of(graph[1], graph) == depth_of(graph[2], graph) == 2


def test_only_units_whose_dependencies_allow_it_are_ready() -> None:
    graph = [
        unit("a", state="planned"),
        unit("b", depends_on=("a",), state="planned"),
    ]

    ready = ready_units(graph, max_concurrent=4, depth_cap=3)

    assert [u.id for u in ready] == ["a"]


def test_a_cross_repo_dependent_waits_for_a_merge_not_just_a_pr() -> None:
    graph = [
        unit("a", repo="platform", state="in_review"),
        unit("b", repo="app", depends_on=("a",), state="planned"),
    ]

    assert ready_units(graph, max_concurrent=4, depth_cap=3) == []


def test_the_depth_cap_holds_back_a_chain_but_not_its_siblings() -> None:
    """The cap bounds how far one line runs ahead of review, not how much
    parallel work is open."""
    graph = [
        unit("a", state="in_review"),
        unit("b", depends_on=("a",), state="in_review"),
        unit("c", depends_on=("b",), state="in_review"),
        unit("deep", depends_on=("c",), state="planned"),
        unit("sibling", state="planned"),
    ]

    ready = ready_units(graph, max_concurrent=4, depth_cap=3)

    assert [u.id for u in ready] == ["sibling"]


def test_concurrency_counts_work_in_flight_not_prs_awaiting_review() -> None:
    """Open PRs are reviewable work, deliberately uncapped. What's capped is
    how many units are being *built* at once."""
    graph = [
        unit("a", state="running"),
        unit("b", state="in_review"),
        unit("c", state="in_review"),
        unit("d", state="planned"),
    ]

    ready = ready_units(graph, max_concurrent=2, depth_cap=3)

    assert [u.id for u in ready] == ["d"]

    assert ready_units(graph, max_concurrent=1, depth_cap=3) == []


@pytest.mark.parametrize("state", ["in_review", "merged", "running", "closed"])
def test_a_unit_that_is_not_planned_is_never_rescheduled(state: str) -> None:
    graph = [unit("a", state=state)]

    assert ready_units(graph, max_concurrent=4, depth_cap=3) == []


def test_a_dependent_waits_for_its_parent_to_finish_reviewing() -> None:
    """A unit is not done when it starts building — it is done when it has
    passed the build/review loop, tier 1, and been pushed. `IN_FLIGHT` includes
    RUNNING, so a dependent was unblocked the moment its parent *began*, and
    would have based itself on a branch that had not been reviewed and might
    not exist yet. The review loop makes that window much wider."""
    graph = [
        unit("c/1", state=RUNNING),
        unit("c/2", depends_on=("c/1",)),
    ]

    ready = ready_units(graph, max_concurrent=4, depth_cap=3)

    assert [u.id for u in ready] == [], "the parent is still building"


def test_a_dependent_starts_once_its_parent_is_open() -> None:
    """Open means the loop finished, tier 1 passed and the branch is pushed —
    which is exactly when there is something to stack on."""
    graph = [unit("c/1", state=IN_REVIEW), unit("c/2", depends_on=("c/1",))]

    ready = ready_units(graph, max_concurrent=4, depth_cap=3)

    assert [u.id for u in ready] == ["c/2"]


def test_an_independent_unit_runs_alongside_a_building_one() -> None:
    """Only dependents wait. Work that needs nothing from the running unit has
    no reason to queue behind it."""
    graph = [unit("c/1", state=RUNNING), unit("c/2"), unit("c/3", depends_on=("c/1",))]

    ready = ready_units(graph, max_concurrent=4, depth_cap=3)

    assert [u.id for u in ready] == ["c/2"]


def test_a_running_parent_is_never_used_as_a_base() -> None:
    """Its branch may not exist yet, and nothing on it has been reviewed."""
    graph = [unit("c/1", state=RUNNING), unit("c/2", depends_on=("c/1",))]

    assert base_of(graph[1], graph) == "main"


def test_the_trunk_is_built_on_from_the_remote_and_unit_branches_locally() -> None:
    """The checkout's `main` is the user's and nothing updates it: building
    on it puts a unit on a main from before its predecessor merged."""
    from agent_build_kit.pipeline.units import local_ref

    assert local_ref("main") == "origin/main"
    assert local_ref("spec/add-marker/1") == "spec/add-marker/1"
