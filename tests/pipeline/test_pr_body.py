"""What a reviewer reads before merging a unit.

The PR is the only surface where the whole picture comes together, and on a
free-plan private repo nothing enforces anything: no required checks, no
blocked merge. So the body has to carry what a human needs in order to decide
— and to notice when they shouldn't merge yet (docs/architecture.md).
"""

from agent_build_kit.pipeline.pr_body import _assumptions, build_pr_body, stack_line
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
    assumptions = _assumptions(unit3, graph)

    assert "ready to merge" in line.lower()
    assert "nothing unmerged" in assumptions.lower()
