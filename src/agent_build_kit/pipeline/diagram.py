"""A mermaid view of every unit, across both repos.

Units are tracked in the planning repo rather than as GitHub issues, so
nothing renders the graph for free. This does, and it is the page to open to
answer the two questions that matter while the pipeline runs: what is in
flight, and what is stuck behind what.

Two drawing decisions carry most of the meaning:

- **Grouped by repo,** because that decides what can stack. Units in one repo
  chain onto each other's branches; across repos they can only wait.
- **Cross-repo edges are dashed,** because they are the slow ones. A same-repo
  dependent starts as soon as its parent has a branch; a cross-repo dependent
  waits for a merge, a pinned-SHA bump and a re-lock.

Rewritten on every change to the unit store (see `cli._store`), so it is
current whenever a tick is running — it used to be written only on request,
and went two days stale unnoticed. Sorted, so a rewrite with nothing changed
is no diff.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.pipeline.shell import repo_slug
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, PLANNED, RUNNING, waiting_on

STATE_STYLES = {
    "planned": "fill:#eef2ff,stroke:#6366f1,color:#1e1b4b",
    "blocked": "fill:#f5f5f4,stroke:#a8a29e,color:#44403c,stroke-dasharray:3 3",
    "running": "fill:#fef3c7,stroke:#d97706,color:#451a03",
    "paused_rework": "fill:#ffedd5,stroke:#ea580c,color:#431407,stroke-dasharray:3 3",
    "paused_usage": "fill:#fef9c3,stroke:#ca8a04,color:#422006,stroke-dasharray:3 3",
    HELD: "fill:#fae8ff,stroke:#a21caf,color:#4a044e",
    IN_REVIEW: "fill:#dbeafe,stroke:#2563eb,color:#172554",
    "merged": "fill:#dcfce7,stroke:#16a34a,color:#052e16",
    "closed": "fill:#fee2e2,stroke:#dc2626,color:#450a0a",
    "failed": "fill:#fecaca,stroke:#b91c1c,color:#450a0a,stroke-width:3px",
    "unplanned": "fill:#f5f5f4,stroke:#a8a29e,color:#44403c",
}


def _node_id(unit_id: str) -> str:
    """Mermaid reads `/` and `-` as syntax, so ids are flattened."""
    return re.sub(r"[^A-Za-z0-9]", "_", unit_id)


def _effective_state(unit: StoredUnit, units: list[StoredUnit]) -> str:
    """What to colour the node.

    A planned unit the scheduler would hold back is *blocked*, not merely
    planned — that distinction is the whole point of the diagram. Asked of the
    scheduler's own rule, which this used to restate and had drifted from: it
    showed a unit as startable while its same-repo parent was still building.
    """
    if unit.state != PLANNED:
        return unit.state

    # Stopped part-way through its loop, rather than never started: the runner
    # records that as a return to planned with a note saying why.
    last = unit.history[-1] if unit.history else {}
    note = str(last.get("note", ""))
    if note.startswith("paused before"):
        # Not gated on `waiting_on`: nothing upstream holds it, only the window.
        return "paused_usage"
    if waiting_on(unit, units):
        return "paused_rework" if note.startswith(("held before", "held after")) else "blocked"
    return PLANNED


def _label(state: str) -> str:
    """How a state reads in a node. Mermaid class names cannot hold the colon."""
    return state.replace("paused_", "paused: ")


# States that are still going somewhere, or stuck until someone looks.
# Everything else is history. Failed is here because it is the state that most
# needs seeing: left out, a unit vanishes from the graph on failing tier 2,
# and takes a merged parent with it when it was the only unit built on it.
ACTIVE = (PLANNED, RUNNING, IN_REVIEW, HELD, "failed")


def in_view(units: list[StoredUnit]) -> list[StoredUnit]:
    """The units worth drawing: unfinished work, and what it directly builds on.

    Every unit ever planned would make the graph grow without bound, and the
    merged ones answer nothing about what is happening now. The exception is
    a merged unit that active work depends on directly — the base it stands
    on. Its ancestors, and closed or unplanned units, are left out.
    """
    active = [unit for unit in units if unit.state in ACTIVE]
    parents = {dep for unit in active for dep in unit.depends_on}
    return [
        unit
        for unit in units
        if unit.state in ACTIVE or (unit.state == MERGED and unit.id in parents)
    ]


def render_mermaid(units: list[StoredUnit], *, graph: list[StoredUnit] | None = None) -> str:
    """Draw `units`. `graph` is the whole store when `units` is a subset of it:
    whether a unit is blocked depends on parents that may not be drawn."""
    graph = graph if graph is not None else units
    index = {unit.id: unit for unit in units}
    ordered = sorted(units, key=lambda unit: (unit.repo, unit.id))

    lines = ["flowchart LR"]

    if not units:
        lines.append('    empty["Nothing in flight"]')

    for repo in sorted({unit.repo for unit in units}):
        lines.append(f"    subgraph {repo}")
        for unit in [u for u in ordered if u.repo == repo]:
            state = _effective_state(unit, graph)
            pr = f" · PR #{unit.pr}" if unit.pr else ""
            label = (
                f"{unit.id}<br/>{unit.title}<br/><small>{unit.tier} · {_label(state)}{pr}</small>"
            )
            lines.append(f'        {_node_id(unit.id)}["{label}"]')
        lines.append("    end")

    for unit in ordered:
        for dependency in sorted(unit.depends_on):
            parent = index.get(dependency)
            if parent is None:
                continue
            # Dashed across repos: that edge cannot be stacked, only waited on.
            arrow = "-->" if parent.repo == unit.repo else "-.->"
            lines.append(f"    {_node_id(dependency)} {arrow} {_node_id(unit.id)}")

    for state, style in STATE_STYLES.items():
        lines.append(f"    classDef {state} {style}")

    for unit in ordered:
        lines.append(f"    class {_node_id(unit.id)} {_effective_state(unit, graph)}")

    return "\n".join(lines)


def render_markdown(units: list[StoredUnit]) -> str:
    """The committed page: the diagram, a legend, and what awaits review."""
    shown = in_view(units)
    hidden = len(units) - len(shown)
    awaiting = [unit for unit in units if unit.state == IN_REVIEW]
    awaiting_lines = (
        "\n".join(
            f"- `{unit.id}` ({unit.repo}) — "
            # Absolute: the PR is in the unit's repo, not the planning repo
            # this page is committed to.
            + (
                f"[#{unit.pr}](https://github.com/{repo_slug(unit.repo)}/pull/{unit.pr})"
                if unit.pr
                else "PR not opened yet"
            )
            for unit in sorted(awaiting, key=lambda u: u.id)
        )
        or "- Nothing is waiting on review."
    )

    return f"""\
# Unit dependency graph

{_count(len(shown), "unit")} in view across {_count(len({u.repo for u in shown}), "repo")};
{hidden} finished, closed or unplanned not shown. Only unfinished work is drawn, with the merged
units it builds on directly. Rewritten whenever a unit changes state; do not
edit by hand.

```mermaid
{render_mermaid(shown, graph=units)}
```

## Legend

- **planned** — ready to start when a slot and the depth cap allow.
- **blocked** — waiting on a dependency. A cross-repo dependency (dashed
  edge) must *merge* first; a same-repo one must be through its build/review
  loop, so there is a reviewed branch to stack on.
- **running** — in the build/review loop: an agent is working in a worktree.
- **paused: rework** — stopped between steps because a unit it depends on
  went back for rework; it restacks and resumes once that unit is through
  review again.
- **paused: usage** — stopped between steps because the usage window passed
  its threshold; it resumes at that step on the first tick after the window
  resets.
- **in_review** — through the build/review loop; its PR is waiting for human
  review. Dependents in the same repo may stack on it. Deliberately uncapped.
- **merged** — done, and no longer counted against its stack's depth.
- **held** — a reviewer took it over; nothing automatic touches it.
- **failed** — stopped on something it could not get past; its feedback says
  what. Nothing retries it until someone requeues it.
- **closed** / **unplanned** — stopped, or dropped from the latest plan while
  still on record.

## Waiting on review

{awaiting_lines}

_Generated {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}._
"""


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def write_page(units: list[StoredUnit], out: Path) -> None:
    """Rewrite the page, keeping the old timestamp when nothing else changed.

    Called on every store write, so without this each tick would leave a
    one-line diff in a committed file for no change at all.
    """
    page = render_markdown(units)
    if out.exists() and _body(out.read_text()) == _body(page):
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)


def _body(page: str) -> str:
    return re.sub(r"_Generated .*_", "", page)


def main(argv: list[str] | None = None) -> int:
    """Write the diagram page from the unit store."""
    import argparse
    from pathlib import Path

    from agent_build_kit.installation import load_installation
    from agent_build_kit.pipeline.unit_store import UnitStore

    installation = load_installation()
    parser = argparse.ArgumentParser(description="Render the unit dependency graph.")
    parser.add_argument("--store", type=Path, default=installation.state_dir / "units.json")
    parser.add_argument("--out", type=Path, default=installation.graph_page)
    args = parser.parse_args(argv)

    units = UnitStore(args.store).all()
    write_page(units, args.out)
    print(f"{args.out}: {len(units)} unit(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
