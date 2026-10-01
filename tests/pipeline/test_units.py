"""Turning a change's task groups into units of work.

A unit is one PR's worth of work in one repo (docs/architecture.md).
Task groups are the raw material; these rules decide where the
boundaries fall, what each unit stacks on, and which ones may run now.

All of it is pure: given a graph, the answers are the same every time. The
planner that produces the graph is a separate concern, and the parts that
touch git and GitHub are separate again.
"""

import pytest

from agent_build_kit import config as config_module
from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    RUNNING,
    base_of,
    branch_name,
    depth_of,
    held_for_base,
    later_groups,
    plan_units,
    ready_units,
    waiting_on,
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
    units = plan_units("add-marker", [group(1), group(2), group(3)], min_lines=500, max_lines=1000)

    assert len(units) == 1
    assert units[0].estimated_lines == 600
    assert units[0].groups == (1, 2, 3)


def test_absorbing_stops_once_the_floor_is_reached() -> None:
    """A floor, not a target: it stops as soon as it's met rather than
    sweeping up everything that follows."""
    units = plan_units(
        "add-marker",
        [group(1, lines=300), group(2, lines=300), group(3)],
        min_lines=500,
        max_lines=1000,
    )

    assert [u.groups for u in units] == [(1, 2), (3,)]


def test_a_group_bigger_than_the_floor_stands_alone() -> None:
    units = plan_units("add-marker", [group(1, lines=900), group(2)], min_lines=500, max_lines=1000)

    assert [u.groups for u in units] == [(1,), (2,)]


def test_a_fan_out_group_ends_its_unit_however_small() -> None:
    """Stopping early is worth it when finishing unblocks other work."""
    units = plan_units(
        "add-marker",
        [group(1, lines=50, fans_out=True), group(2)],
        min_lines=500,
        max_lines=1000,
    )

    assert [u.groups for u in units] == [(1,), (2,)]


def test_units_never_span_repos() -> None:
    """A branch lives in one repo, so a unit does too — even when both groups
    are tiny and would otherwise be absorbed."""
    units = plan_units(
        "add-marker",
        [group(1, repo="platform", lines=50), group(2, repo="app", lines=50)],
        min_lines=500,
        max_lines=1000,
    )

    assert [(u.repo, u.groups) for u in units] == [("platform", (1,)), ("app", (2,))]


def test_tiers_do_not_split_a_unit() -> None:
    """Test tier decides how a unit is verified, not what belongs together."""
    units = plan_units(
        "add-marker",
        [group(1, tier="tier1", lines=200), group(2, tier="tier2", lines=200)],
        min_lines=300,
        max_lines=1000,
    )

    assert len(units) == 1
    assert units[0].tier == "tier2", "a unit needing the stack anywhere needs it overall"


def test_units_depend_on_the_one_before_them_in_the_same_repo() -> None:
    units = plan_units(
        "add-marker",
        [group(1, lines=600), group(2, lines=600), group(3, repo="platform")],
        min_lines=500,
        max_lines=1000,
    )

    assert units[1].depends_on == (units[0].id,)
    assert units[2].depends_on == (units[1].id,), "cross-repo order is still order"


def test_groups_are_not_combined_past_the_ceiling() -> None:
    """The floor would keep absorbing a 400-line group into the next; the
    ceiling says 1,100 lines is past what one PR should carry, so they split
    even though the first is under the floor on its own."""
    units = plan_units(
        "add-marker",
        [group(1, lines=400), group(2, lines=700), group(3, lines=200)],
        min_lines=500,
        max_lines=1000,
    )

    assert [u.groups for u in units] == [(1,), (2,), (3,)]
    assert all(u.estimated_lines <= 1000 for u in units)


def test_under_the_ceiling_the_floor_still_groups() -> None:
    """The ceiling bounds grouping from above without stopping small groups
    being combined below it: the first two still go together, and only the
    700-line group that would take them past 1,000 starts a unit of its own."""
    units = plan_units(
        "add-marker",
        [group(1, lines=200), group(2, lines=200), group(3, lines=700), group(4, lines=200)],
        min_lines=500,
        max_lines=1000,
    )

    assert [u.groups for u in units] == [(1, 2), (3,), (4,)]


def test_branch_names_are_deterministic() -> None:
    """A re-run must reuse the branch and keep the work already on it, so the
    name can't carry a timestamp or a slug that drifts."""
    first = branch_name(unit("add-marker/2"))
    again = branch_name(unit("add-marker/2", title="renamed since"))

    assert first == again == "spec/add-marker/2"


def test_a_unit_with_no_open_dependency_starts_from_main() -> None:
    graph = [unit("a", state="merged"), unit("b", depends_on=("a",))]

    assert base_of(graph[1], graph) == "main"


def on_branch(repo: str, branch: str) -> None:
    """Activate the workspace with `repo`'s default branch set, as abk.yaml would."""
    current = config_module.active()
    repos = {
        name: entry.model_copy(update={"default_branch": branch}) if name == repo else entry
        for name, entry in current.repos.items()
    }
    config_module.activate(current.model_copy(update={"repos": repos}), config_module.active_root())


def test_a_unit_starts_from_its_repo_s_own_default_branch() -> None:
    """`default_branch` is what units are built on and what their PRs target.
    It was written into abk.yaml and read by the doctor, and the pipeline
    started every unit from a literal `main` regardless — so a repo that
    integrates on `dev` had its units built on a branch that lacks the code
    they change, and proposed into the wrong place."""
    on_branch("app", "dev")
    graph = [unit("a", state="merged"), unit("b", depends_on=("a",))]

    assert base_of(graph[1], graph) == "dev"


def test_each_repo_starts_from_its_own_default_branch() -> None:
    on_branch("app", "dev")
    graph = [unit("a", repo="platform"), unit("b", repo="app")]

    assert base_of(graph[0], graph) == "main"
    assert base_of(graph[1], graph) == "dev"


def test_stacking_still_beats_the_default_branch() -> None:
    """An open dependency in the same repo is the base whatever the trunk is —
    that is what keeps two units from duplicating or conflicting."""
    on_branch("app", "dev")
    graph = [
        unit("add-marker/1", state="in_review"),
        unit("add-marker/2", depends_on=("add-marker/1",)),
    ]

    assert base_of(graph[1], graph) == "spec/add-marker/1"


def test_a_repo_the_workspace_does_not_name_falls_back_to_main() -> None:
    """A unit whose repo is not in abk.yaml cannot be built anyway, but asking
    where it would start must not raise."""
    assert base_of(unit("z", repo="nowhere"), [unit("z", repo="nowhere")]) == "main"


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


def test_a_satisfied_unit_is_transparent_to_base_of() -> None:
    """Unit 2 added nothing of its own and was judged satisfied on unit 1's
    branch — it has no branch of its own to stack on, so unit 3 stacks
    straight through it onto unit 1, and onto main once unit 1 has merged."""
    graph = [
        unit("c/1", state="in_review"),
        unit("c/2", depends_on=("c/1",), state="satisfied"),
        unit("c/3", depends_on=("c/2",)),
    ]

    assert base_of(graph[2], graph) == branch_name(graph[0])

    merged = [u.model_copy(update={"state": "merged"}) if u.id == "c/1" else u for u in graph]
    assert base_of(merged[2], merged) == "main"


def test_a_cross_repo_dependent_of_a_satisfied_unit_stops_waiting() -> None:
    """A satisfied unit never merges — it added nothing, so it never opened a
    PR — but its work already landed wherever its own same-repo dependency
    did, or nowhere in particular if it had none. Either way a cross-repo
    dependent, which cannot stack on it, is released rather than waiting for
    a merge that will never come."""
    graph = [
        unit("a", repo="platform", state="satisfied"),
        unit("b", repo="app", depends_on=("a",)),
    ]

    assert waiting_on(graph[1], graph) == []


def test_a_cross_repo_dependent_of_a_satisfied_unit_still_waits_for_its_own_work() -> None:
    """A satisfied unit's own same-repo dependency has not merged yet, so its
    work has not actually landed anywhere a cross-repo dependent could see."""
    graph = [
        unit("a1", repo="platform", state="in_review"),
        unit("a2", repo="platform", depends_on=("a1",), state="satisfied"),
        unit("b", repo="app", depends_on=("a2",)),
    ]

    assert waiting_on(graph[2], graph) == [graph[1]]


@pytest.mark.parametrize("state", ["planned", "running", "failed", "held", "closed"])
def test_a_dependent_waits_through_a_satisfied_unit_for_its_predecessor(state: str) -> None:
    """Unit 2 worked ahead of unit 1, which is back to being built (or stuck).
    Unit 3, depending on 2, has nothing to stack on: it waits on unit 1, not
    on a satisfied unit that is transparent."""
    graph = [
        unit("c/1", state=state),
        unit("c/2", depends_on=("c/1",), state="satisfied"),
        unit("c/3", depends_on=("c/2",)),
    ]

    assert waiting_on(graph[2], graph) == [graph[0]]
    assert graph[2] not in ready_units(graph, max_concurrent=5, depth_cap=5)


@pytest.mark.parametrize("state", ["in_review", "merged"])
def test_a_dependent_of_a_satisfied_unit_starts_once_its_predecessor_is_reviewed(
    state: str,
) -> None:
    graph = [
        unit("c/1", state=state),
        unit("c/2", depends_on=("c/1",), state="satisfied"),
        unit("c/3", depends_on=("c/2",)),
    ]

    assert waiting_on(graph[2], graph) == []
    assert graph[2] in ready_units(graph, max_concurrent=5, depth_cap=5)


@pytest.mark.parametrize("state", ["planned", "running", "in_review", "held"])
def test_a_same_repo_merge_gated_dependency_must_merge_first(state: str) -> None:
    graph = [
        unit("c/1", state=state),
        unit("c/2", depends_on=("c/1",), merge_before=("c/1",)),
    ]

    assert waiting_on(graph[1], graph) == [graph[0]]
    assert graph[1] not in ready_units(graph, max_concurrent=5, depth_cap=5)


def test_a_merged_dependency_releases_the_dependent_onto_the_trunk() -> None:
    graph = [
        unit("c/1", state="merged"),
        unit("c/2", depends_on=("c/1",), merge_before=("c/1",)),
    ]

    assert waiting_on(graph[1], graph) == []
    assert graph[1] in ready_units(graph, max_concurrent=5, depth_cap=5)
    assert base_of(graph[1], graph) == "main"


def test_a_satisfied_merge_gated_dependency_with_its_work_landed_releases_the_dependent() -> None:
    graph = [
        unit("c/1", state="satisfied"),
        unit("c/2", depends_on=("c/1",), merge_before=("c/1",)),
    ]

    assert waiting_on(graph[1], graph) == []


def test_a_merge_gated_dependency_is_waited_on_even_when_it_has_no_review_branch_yet() -> None:
    """Only the gated dependency holds the dependent; an ordinary one in review
    still lets it start."""
    graph = [
        unit("c/1", state="in_review"),
        unit("d/1", change="d", state="in_review"),
        unit("c/2", depends_on=("c/1", "d/1"), merge_before=("d/1",)),
    ]

    assert waiting_on(graph[2], graph) == [graph[1]]


def test_an_unqualified_same_repo_dependency_in_review_still_lets_the_dependent_start() -> None:
    graph = [unit("c/1", state="in_review"), unit("c/2", depends_on=("c/1",))]

    assert waiting_on(graph[1], graph) == []
    assert base_of(graph[1], graph) != "main", "stacked on the dependency's branch"


def test_later_groups_excludes_this_unit_and_other_changes() -> None:
    graph = [
        unit("add-marker/1", groups=(1,)),
        unit("add-marker/2", groups=(3, 2), depends_on=("add-marker/1",)),
        unit("other/1", change="other", groups=(9,)),
    ]

    assert later_groups(graph[0], graph) == (2, 3)


def test_later_groups_is_empty_for_the_last_unit() -> None:
    graph = [unit("add-marker/1", groups=(1,)), unit("add-marker/2", groups=(2,))]

    assert later_groups(graph[1], graph) == ()


def test_later_groups_ignores_a_unit_the_plan_dropped() -> None:
    """A group the plan no longer assigns to anyone is not later work — naming
    it as belonging to a later unit would leave it looking spoken for."""
    graph = [
        unit("add-marker/1", groups=(1,)),
        unit("add-marker/2", groups=(2,), state="unplanned"),
    ]

    assert later_groups(graph[0], graph) == ()


def test_later_groups_counts_from_a_changes_highest_group_across_every_member() -> None:
    """A chain of joins gives members [a:1, b:1, a:3]: group 2 of `a` sits
    before the 3 this unit builds, so it is not later work."""
    from agent_build_kit.pipeline.units import Member

    graph = [
        unit(
            "a/1",
            change="a",
            groups=(1,),
            joined=(Member(change="b", groups=(1,)), Member(change="a", groups=(3,))),
        ),
        unit("a/2", change="a", groups=(2,)),
        unit("a/3", change="a", groups=(4,)),
    ]

    assert later_groups(graph[0], graph) == (4,)


def test_the_trunk_is_built_on_from_the_remote_and_unit_branches_locally() -> None:
    """The checkout's `main` is the user's and nothing updates it: building
    on it puts a unit on a main from before its predecessor merged."""
    from agent_build_kit.pipeline.units import local_ref

    assert local_ref("main") == "origin/main"
    assert local_ref("spec/add-marker/1") == "spec/add-marker/1"


def test_a_hold_for_a_changed_base_is_told_apart_from_other_holds() -> None:
    """The scheduler starts a held unit again in the same pass only when what
    held it is gone: a changed base is, because resuming restacks first."""
    assert held_for_base(
        "held before rework_review: its base moved from spec/a/1 to dev while it built"
    )
    assert held_for_base("held after implement: its base spec/a/1 was rewritten while it built")
    assert not held_for_base("held before implement: upstream a/1 is not in review yet")
    assert not held_for_base("held before implement: the usage window filled")
    assert not held_for_base("rework requested: merge conflict with its base")
    assert not held_for_base("paused before implement: usage")


def test_the_reasons_a_build_gives_for_a_changed_base_come_from_the_shared_prefix() -> None:
    """Reword either reason in `wiring` without the constant and re-admission
    quietly stops matching it; this is what would notice."""
    import inspect

    from agent_build_kit.pipeline import wiring

    source = inspect.getsource(wiring.build_base_moved)

    assert source.count("{BASE_CHANGED}") == 2
