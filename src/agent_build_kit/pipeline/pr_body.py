"""The PR description: everything a reviewer needs in one place.

On a free-plan private repo GitHub enforces nothing — no required checks, no
blocked merge, no approval state. The PR body is therefore not decoration; it
is the only place where the stack position, the test evidence and the
provisional parts of the work come together where a human will see them
(docs/architecture.md).

Three things it must always say:

- **Where this sits in the stack,** because merging out of order is the
  easiest mistake to make — unless the host renders the stack itself, when the
  body says only whether the chain is linear, which the host does not.
- **What it assumes,** since a unit stacked on unmerged work is built on
  something that may still change.
- **How it was verified,** including the tier 2 snapshot, which no CI run can
  reproduce.
"""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit import forges
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import MERGED, through_satisfied, trunk_of


def _unmerged(unit: StoredUnit, graph: list[StoredUnit]) -> list[StoredUnit]:
    """What this unit depends on that has not merged yet."""
    index = {item.id: item for item in graph}
    return [
        index[dep]
        for dep in through_satisfied(unit, graph)
        if dep in index and index[dep].state != MERGED
    ]


def stack_line(unit: StoredUnit, graph: list[StoredUnit], *, base: str) -> str:
    """One line describing what this PR sits on, and whether it may merge."""
    unmerged = _unmerged(unit, graph)

    if not unmerged:
        return (
            f"Based on `{base}`, with nothing unmerged beneath it — "
            "**ready to merge** whenever the checks look right."
        )

    parents = ", ".join(
        f"`{parent.id}`" + (f" (#{parent.pr})" if parent.pr else "") for parent in unmerged
    )
    return (
        f"Stacked on `{base}`. **Merge {parents} first** — merging this one "
        "ahead of them would pull their commits in with it."
    )


def assumptions(unit: StoredUnit, graph: list[StoredUnit], trunk: str = "main") -> str:
    """The PR body's statement of what the unit assumes about the units beneath it:
    which are still unmerged, or that nothing is."""
    unmerged = _unmerged(unit, graph)

    if not unmerged:
        return (
            f"This unit assumes nothing unmerged: everything it builds on is already in `{trunk}`."
        )

    lines = []
    for parent in unmerged:
        where = f"#{parent.pr}" if parent.pr else "not yet opened"
        lines.append(
            f"- Builds on `{parent.id}` ({parent.repo}, {where}), which has not merged yet. "
            "If that PR changes in review, this one is restacked and re-verified."
        )
    return "\n".join(lines)


def _scope_lines(unit: StoredUnit) -> str:
    """What the unit builds: each change with its groups, and where its spec is."""
    first, *carried = unit.members()
    groups = ", ".join(str(group) for group in first.groups) or "—"
    lines = [
        f"Unit `{unit.id}` of change **{first.change}**, task group(s) {groups}.",
        f"Spec: `openspec/changes/{first.change}/` in the planning repo.",
    ]
    for member in carried:
        numbers = ", ".join(str(group) for group in member.groups)
        lines.append(
            f"Also carries task group(s) {numbers} of change **{member.change}**. "
            f"Spec: `openspec/changes/{member.change}/` in the planning repo."
        )
    return "\n".join(lines)


def build_pr_body(
    unit: StoredUnit,
    *,
    graph: list[StoredUnit],
    base: str,
    tier2_snapshot: str | None = None,
    restack_note: str | None = None,
    open_points: str | None = None,
    follow_ups: list[str] | None = None,
    stacks: bool = False,
    linear: bool = True,
) -> str:
    """The full description for a unit's PR."""
    if unit.tier == "tier2":
        verification = (
            tier2_snapshot
            or "## Tier 2 results\n\n_Not recorded — this PR should not have been pushed._"
        )
    else:
        ci = forges.for_repo(unit.repo)[0].ci_name
        verification = (
            "## Verification\n\n"
            "This is a **tier 1** unit: everything it needs is fakes, fixtures or "
            f"throwaway containers, so {ci} runs the whole of it. No tier 2 run was required."
        )

    restack = f"\n## What moved underneath this\n\n{restack_note}\n" if restack_note else ""
    open_points_block = (
        f"\n## Held for a person\n\nReview's rounds ran out with this still outstanding:\n\n"
        f"{open_points}\n"
        if open_points
        else ""
    )
    follow_ups_block = (
        "\n## Left for later\n\nApproved, with these recorded rather than blocking:\n\n"
        + "\n".join(f"- {item}" for item in follow_ups)
        + "\n"
        if follow_ups
        else ""
    )

    # Where the host renders the stack, it shows the order and what is beneath
    # this PR; repeated here, the pipeline's copy is the one that goes stale.
    # Linearity it does not show until the merge button is disabled. On the
    # trunk there is no chain beneath to be linear or not, and `stack_line`
    # says what matters: that it is ready to merge.
    line = stack_line(unit, graph, base=base)
    beneath = _unmerged(unit, graph)
    if not beneath:
        position = line
    elif not linear:
        linearity = (
            "**The chain is not linear**: this branch no longer sits on the one below "
            "it, so it cannot be merged until the pipeline rebases it."
        )
        position = linearity if stacks else f"{line}\n\n{linearity}"
    elif stacks:
        position = "The chain beneath this is linear: this branch sits on the one below it."
    else:
        position = line
    if stacks and beneath:
        # What it is waiting for, without restating where it sits.
        position += " It merges after everything beneath it in the stack has merged."
    order = "the stack order the host shows" if stacks else "the stack order above"

    return f"""\
{position}

{_scope_lines(unit)}

## Assumptions

{assumptions(unit, graph, trunk_of(unit.repo))}

{verification}
{restack}{open_points_block}{follow_ups_block}
## How this was built

Tests were committed first and seen to fail before any implementation
existed; the commit order is checked mechanically before the push. Lint,
formatting and types pass at the tip.

---

_Opened by the spec-driven pipeline. It never merges its own PRs — a human
merges every one, after checking {order}._
"""


def _landed_elsewhere(unit: StoredUnit, graph: Sequence[StoredUnit]) -> StoredUnit | None:
    """The same-repo predecessor whose branch already carried this unit's
    work, if the graph can say.

    A unit that reaches `satisfied` built on some base — its nearest same-repo
    dependency, looked through any satisfied one in between (`through_satisfied`,
    the same lookup `base_of` uses). That predecessor is where the work landed;
    a unit with no same-repo dependency in the graph answers None rather than
    guessing.
    """
    index = {item.id: item for item in graph}
    for dep_id in through_satisfied(unit, graph):
        dep = index.get(dep_id)
        if dep is not None and dep.repo == unit.repo:
            return dep
    return None


def satisfied_reason(unit: StoredUnit, *, graph: Sequence[StoredUnit]) -> str:
    """Why a satisfied unit's stale pull request is closing.

    Composed here, mechanically, rather than asked of a model: the judgement
    that got the unit here (no commits of its own, tier 1 green at the tip) is
    already mechanical, and this is the same kind of text `build_pr_body`
    writes without a model call.
    """
    covered = " and ".join(
        f"{', '.join(str(group) for group in member.groups) or '—'} of change `{member.change}`"
        for member in unit.members()
    )
    landed = _landed_elsewhere(unit, graph)
    where = ""
    if landed is not None:
        where = f" — it landed in `{landed.id}`" + (f" (#{landed.pr})" if landed.pr else "")
    return (
        f"Task group(s) {covered} were already implemented "
        f"elsewhere{where}. There is nothing here for this pull request to add, so it is "
        "closing — its tasks are ticked in tasks.md all the same."
    )
