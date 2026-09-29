"""The PR description: everything a reviewer needs in one place.

On a free-plan private repo GitHub enforces nothing — no required checks, no
blocked merge, no approval state. The PR body is therefore not decoration; it
is the only place where the stack position, the test evidence and the
provisional parts of the work come together where a human will see them
(docs/architecture.md).

Three things it must always say:

- **Where this sits in the stack,** because merging out of order is the
  easiest mistake to make and GitHub shows nothing about stacks.
- **What it assumes,** since a unit stacked on unmerged work is built on
  something that may still change.
- **How it was verified,** including the tier 2 snapshot, which no CI run can
  reproduce.
"""

from __future__ import annotations

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import MERGED


def stack_line(unit: StoredUnit, graph: list[StoredUnit], *, base: str) -> str:
    """One line describing what this PR sits on, and whether it may merge."""
    index = {item.id: item for item in graph}
    unmerged = [
        index[dep] for dep in unit.depends_on if dep in index and index[dep].state != MERGED
    ]

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


def _assumptions(unit: StoredUnit, graph: list[StoredUnit]) -> str:
    index = {item.id: item for item in graph}
    unmerged = [
        index[dep] for dep in unit.depends_on if dep in index and index[dep].state != MERGED
    ]

    if not unmerged:
        return "This unit assumes nothing unmerged: everything it builds on is already in `main`."

    lines = []
    for parent in unmerged:
        where = f"#{parent.pr}" if parent.pr else "not yet opened"
        lines.append(
            f"- Builds on `{parent.id}` ({parent.repo}, {where}), which has not merged yet. "
            "If that PR changes in review, this one is restacked and re-verified."
        )
    return "\n".join(lines)


def build_pr_body(
    unit: StoredUnit,
    *,
    graph: list[StoredUnit],
    base: str,
    tier2_snapshot: str | None = None,
    restack_note: str | None = None,
) -> str:
    """The full description for a unit's PR."""
    groups = ", ".join(str(group) for group in unit.groups) or "—"

    if unit.tier == "tier2":
        verification = (
            tier2_snapshot
            or "## Tier 2 results\n\n_Not recorded — this PR should not have been pushed._"
        )
    else:
        verification = (
            "## Verification\n\n"
            "This is a **tier 1** unit: everything it needs is fakes, fixtures or "
            "throwaway containers, so GitHub Actions runs the whole of it. No tier 2 "
            "run was required."
        )

    restack = f"\n## What moved underneath this\n\n{restack_note}\n" if restack_note else ""

    return f"""\
{stack_line(unit, graph, base=base)}

Unit `{unit.id}` of change **{unit.change}**, task group(s) {groups}.
Spec: `openspec/changes/{unit.change}/` in the planning repo.

## Assumptions

{_assumptions(unit, graph)}

{verification}
{restack}
## How this was built

Tests were committed first and seen to fail before any implementation
existed; the commit order is checked mechanically before the push. Lint,
formatting and types pass at the tip.

---

_Opened by the spec-driven pipeline. It never merges its own PRs — a human
merges every one, after checking the stack order above._
"""
