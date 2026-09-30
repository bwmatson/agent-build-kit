"""What a reviewer reads before merging a unit.

The PR is the only surface where the whole picture comes together, and on a
free-plan private repo nothing enforces anything: no required checks, no
blocked merge. So the body has to carry what a human needs in order to decide
— and to notice when they shouldn't merge yet (docs/architecture.md).
"""

import pytest

from agent_build_kit.pipeline.pr_body import (
    assumptions,
    build_pr_body,
    satisfied_reason,
    stack_line,
)
from tests.factories import stored_unit as unit


def test_the_body_names_the_change_it_came_from() -> None:
    """A reviewer's first question is what this is for, and the answer lives
    in the planning repo rather than in the diff."""
    body = build_pr_body(unit(), graph=[unit()], base="main")

    assert "add-marker" in body
    assert "openspec/changes/add-marker" in body


def test_the_stack_position_is_stated_plainly() -> None:
    """Merging out of order is the easiest mistake to make here, and GitHub
    shows nothing about a stack."""
    parent = unit("add-marker/1", depends_on=(), state="in_review", pr=4)
    child = unit("add-marker/2", depends_on=("add-marker/1",))

    line = stack_line(child, [parent, child], base="spec/add-marker/1")

    assert "#4" in line
    assert "spec/add-marker/1" in line


def test_a_bottom_of_stack_unit_says_so() -> None:
    line = stack_line(unit(depends_on=()), [unit(depends_on=())], base="main")

    assert "main" in line
    assert "ready to merge" in line.lower()


def test_a_stacked_unit_warns_against_merging_first() -> None:
    """The one thing that actually breaks a stack."""
    parent = unit("add-marker/1", depends_on=(), state="in_review", pr=4)
    child = unit("add-marker/2", depends_on=("add-marker/1",))

    line = stack_line(child, [parent, child], base="spec/add-marker/1")

    assert "#4" in line
    assert "merge" in line.lower()


def test_the_tier_two_snapshot_is_included_when_there_is_one() -> None:
    body = build_pr_body(
        unit(tier="tier2"),
        graph=[unit()],
        base="main",
        tier2_snapshot="## Tier 2 results\nall good",
    )

    assert "## Tier 2 results" in body


def test_a_tier_one_unit_says_ci_covers_it() -> None:
    """Silence about tier 2 would read as "not run" rather than "not needed"."""
    body = build_pr_body(unit(tier="tier1"), graph=[unit()], base="main")

    assert "tier 1" in body.lower()
    assert "Actions" in body


def test_assumptions_are_stated_so_provisional_work_is_visible() -> None:
    """A unit stacked on unmerged work is built on something that may change.
    Saying so is what lets a reviewer tell solid from provisional."""
    parent = unit("add-marker/1", depends_on=(), state="in_review", pr=4)
    child = unit("add-marker/2", depends_on=("add-marker/1",))

    body = build_pr_body(child, graph=[parent, child], base="spec/add-marker/1")

    assert "Assumptions" in body
    assert "add-marker/1" in body


def test_a_unit_with_no_unmerged_dependencies_says_it_assumes_nothing() -> None:
    body = build_pr_body(unit(depends_on=()), graph=[unit(depends_on=())], base="main")

    assert "Assumptions" in body
    assert "nothing unmerged" in body.lower()


def test_the_body_says_the_agent_will_not_merge_it() -> None:
    """GitHub can't enforce that on this plan, so the PR says it instead."""
    body = build_pr_body(unit(), graph=[unit()], base="main")

    assert "never merges" in body.lower() or "human" in body.lower()


def test_blast_radius_notes_appear_after_a_restack() -> None:
    """When a lower PR changes, a reviewer needs to know what moved
    underneath this one rather than re-reading the diff to find out."""
    body = build_pr_body(
        unit(),
        graph=[unit()],
        base="main",
        restack_note="Rebased onto spec/add-marker/1 after its review fix; no conflicts.",
    )

    assert "Rebased onto" in body
    assert "no conflicts" in body


def test_open_points_appear_when_the_rounds_ran_out() -> None:
    """A person inheriting a held unit needs the outstanding points in the PR,
    not just a state on disk."""
    body = build_pr_body(
        unit(),
        graph=[unit()],
        base="main",
        open_points="the lock is not released on error",
    )

    assert "the lock is not released on error" in body


def test_deferred_follow_ups_appear_when_approval_recorded_them() -> None:
    body = build_pr_body(
        unit(),
        graph=[unit()],
        base="main",
        follow_ups=["Name the lock after what it guards"],
    )

    assert "Name the lock after what it guards" in body


def test_the_body_records_which_task_groups_it_covers() -> None:
    body = build_pr_body(unit(groups=(2, 3)), graph=[unit()], base="main")

    assert "2, 3" in body


def test_stack_line_looks_through_a_satisfied_parent() -> None:
    """A satisfied unit never opens a PR: naming it as the thing to merge
    first would tell a reviewer to wait on a PR that will never exist."""
    unit1 = unit("scope/1", depends_on=(), state="in_review", pr=4)
    unit2 = unit("scope/2", depends_on=("scope/1",), state="satisfied")
    unit3 = unit("scope/3", depends_on=("scope/2",))
    graph = [unit1, unit2, unit3]

    line = stack_line(unit3, graph, base="spec/scope/1")

    assert "scope/1" in line
    assert "scope/2" not in line


def test_stack_line_and_assumptions_clear_once_the_satisfied_chain_merges() -> None:
    """Once unit1 merges, unit2 (satisfied on it) has nothing left unmerged
    behind it either — the stack line should not keep pointing at unit2
    forever."""
    unit1 = unit("scope/1", depends_on=(), state="merged", pr=4)
    unit2 = unit("scope/2", depends_on=("scope/1",), state="satisfied")
    unit3 = unit("scope/3", depends_on=("scope/2",))
    graph = [unit1, unit2, unit3]

    line = stack_line(unit3, graph, base="main")
    stated = assumptions(unit3, graph)

    assert "ready to merge" in line.lower()
    assert "nothing unmerged" in stated.lower()


def test_the_satisfied_reason_names_its_groups_and_says_elsewhere() -> None:
    """A reviewer reading a closed PR needs to know why, without digging: what
    this unit was for, and that it was not this PR that made it unnecessary."""
    satisfied = unit("scope/2", groups=(2, 3), state="satisfied")

    reason = satisfied_reason(satisfied, graph=[satisfied])

    assert "2" in reason and "3" in reason
    assert "implemented elsewhere" in reason.lower()


def test_the_satisfied_reason_says_its_tasks_are_ticked() -> None:
    """The pull request is closing with nothing merged from it, so the
    reason has to say the change's tasks are done some other way — otherwise
    a reader sees a closed PR and ticked boxes with nothing tying them
    together."""
    satisfied = unit("scope/1", groups=(1,), state="satisfied")

    reason = satisfied_reason(satisfied, graph=[satisfied])

    assert "ticked" in reason.lower()


def test_the_satisfied_reason_names_where_the_graph_can_say() -> None:
    """The predecessor this unit stacked on is where the work landed — found
    through the same same-repo dependency the base and the stack line use."""
    predecessor = unit("scope/1", depends_on=(), state="in_review", pr=4)
    satisfied = unit("scope/2", depends_on=("scope/1",), groups=(2,), state="satisfied")

    reason = satisfied_reason(satisfied, graph=[predecessor, satisfied])

    assert "scope/1" in reason
    assert "#4" in reason


def test_the_satisfied_reason_says_nothing_it_cannot_tell() -> None:
    """No same-repo dependency in the graph — nowhere to point a reviewer, so
    the reason says only what it knows rather than guessing."""
    satisfied = unit("scope/1", depends_on=(), groups=(1,), state="satisfied")

    reason = satisfied_reason(satisfied, graph=[satisfied])

    assert "landed in" not in reason


def test_the_satisfied_reason_looks_through_a_satisfied_predecessor() -> None:
    """A satisfied unit never carries its own PR — the same `through_satisfied`
    lookup `base_of` and `stack_line` use finds the real, still-open ancestor."""
    grandparent = unit("scope/1", depends_on=(), state="in_review", pr=9)
    parent = unit("scope/2", depends_on=("scope/1",), state="satisfied")
    satisfied = unit("scope/3", depends_on=("scope/2",), groups=(3,), state="satisfied")

    reason = satisfied_reason(satisfied, graph=[grandparent, parent, satisfied])

    assert "scope/1" in reason
    assert "#9" in reason


# --- a host that renders the stack itself ---------------------------------------


def _chain():
    parent = unit("add-marker/1", depends_on=(), state="in_review", pr=4)
    child = unit("add-marker/2", depends_on=("add-marker/1",))
    return parent, child


def test_on_a_host_with_stacks_the_body_leaves_the_order_to_the_host() -> None:
    """Two sources of one truth, and the pipeline's is the one that goes
    stale. Where the host has no stacks, the body is exactly today's."""
    parent, child = _chain()
    today = build_pr_body(child, graph=[parent, child], base="spec/add-marker/1")

    without = build_pr_body(child, graph=[parent, child], base="spec/add-marker/1", stacks=False)
    with_stacks = build_pr_body(child, graph=[parent, child], base="spec/add-marker/1", stacks=True)

    assert without == today
    assert stack_line(child, [parent, child], base="spec/add-marker/1") not in with_stacks
    assert "Stacked on" not in with_stacks
    assert "first" not in with_stacks.split("## Assumptions")[0].lower(), (
        "no merge-order instruction: the host shows the order"
    )
    assert "linear" in with_stacks.lower(), "it says what the host cannot: that the chain is linear"
    assert "not linear" not in with_stacks.lower()


@pytest.mark.parametrize("stacks", [True, False], ids=["with-stacks", "without-stacks"])
def test_a_chain_left_non_linear_says_so_either_way(stacks: bool) -> None:
    """A non-linear chain cannot be merged until it is rebased; a reviewer
    should read that, not infer it from a disabled button."""
    parent, child = _chain()

    body = build_pr_body(
        child, graph=[parent, child], base="spec/add-marker/1", stacks=stacks, linear=False
    )

    assert "not linear" in body.lower()
    assert "rebase" in body.lower()


def test_a_unit_on_the_trunk_is_ready_to_merge_whichever_host() -> None:
    """Nothing unmerged is beneath it, so there is no chain to call linear —
    and what a reviewer needs is that it can merge now."""
    body = build_pr_body(unit(), graph=[unit()], base="main", stacks=True)

    assert "sits on the one below it" not in body
    assert "ready to merge" in body


def test_on_a_host_with_stacks_the_body_still_says_what_it_waits_for() -> None:
    """Without naming its position: that is the host's to show."""
    parent, child = _chain()

    body = build_pr_body(child, graph=[parent, child], base="spec/add-marker/1", stacks=True)
    opening = body.split("Unit `")[0]

    assert "merges after everything beneath it" in opening
    assert "add-marker/1" not in opening
