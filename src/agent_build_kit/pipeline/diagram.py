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
- **Nested by project** within a repo that has several, because the limits count each
  project on its own. A repo with one project is drawn flat.

Rewritten on every change to the unit store (see `cli._store`), so it is
current whenever a tick is running — it used to be written only on request,
and went two days stale unnoticed. Sorted, so a rewrite with nothing changed
is no diff.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit import forges
from agent_build_kit.config import active
from agent_build_kit.pipeline.unit_store import StoredUnit, backoff_ends, waiting_for
from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    dependency_wait,
    failed_waiting,
    merge_parents,
    priority_note,
    second_parent_wait,
    shown_dependencies,
    shown_waits,
)
from agent_build_kit.pipeline.vocabulary import STATES, ChecksOf, effective_state


def _carried(unit: StoredUnit) -> str:
    """A line per change the unit carries, with its groups; nothing for a plain unit."""
    return "".join(
        f"{member.change}: {', '.join(str(g) for g in member.groups)}<br/>"
        for member in unit.joined
    )


def _waiting(unit: StoredUnit) -> str:
    """What a parked unit waits for, the step it stopped at and when it may run again: a
    clock time, not a countdown, so an unchanged graph is not rewritten each time it is drawn."""
    if not (why := waiting_for(unit)):
        return ""
    at = f" at {unit.step}" if unit.step else ""
    ends = backoff_ends(unit)
    retry = f", retry after {ends:%H:%M} UTC" if ends else ""
    return f" · {why}{at}{retry}"


def _node_id(unit_id: str) -> str:
    """Mermaid reads `/` and `-` as syntax, so ids are flattened."""
    return re.sub(r"[^A-Za-z0-9]", "_", unit_id)


def _project_id(repo: str, project: str) -> str:
    """A nested subgraph's id; the `__project__` infix keeps it apart from a repo's or a unit's."""
    return f"{_node_id(repo)}__project__{_node_id(project)}"


# States that are still going somewhere, or stuck until someone looks.
# Everything else is history. Failed is here because it is the state that most
# needs seeing: left out, a unit vanishes from the graph on failing e2e-test,
# and takes a merged parent with it when it was the only unit built on it.
ACTIVE = (PLANNED, RUNNING, IN_REVIEW, HELD, "failed")


def in_view(units: list[StoredUnit]) -> list[StoredUnit]:
    """The units worth drawing: unfinished work, and what it directly builds on.

    Every unit ever planned would make the graph grow without bound, and the
    merged ones answer nothing about what is happening now. The exception is
    a merged or satisfied unit that active work depends on directly — the
    base it stands on, or, for a satisfied one, the unit whose branch its
    dependent actually stacks on. Left out either way, a dependent would show
    an edge pointing at a node that isn't drawn. Its ancestors, and closed or
    unplanned units, are left out.
    """
    active = [unit for unit in units if unit.state in ACTIVE]
    parents = {dep for unit in active for dep in shown_dependencies(unit, units)}
    return [
        unit
        for unit in units
        if unit.state in ACTIVE or (unit.state in (MERGED, SATISFIED) and unit.id in parents)
    ]


def render_mermaid(
    units: list[StoredUnit],
    *,
    graph: list[StoredUnit] | None = None,
    checks_of: ChecksOf | None = None,
    paused: Collection[str] = (),
    gated: Collection[str] = (),
    restacking: Mapping[str, str] | None = None,
    projects: Mapping[str, Collection[str]] | None = None,
) -> str:
    """Draw `units`. `graph` is the whole store when `units` is a subset of it:
    whether a unit is blocked depends on parents that may not be drawn. `restacking` names
    the base of each unit the restack lane holds. `projects` maps a repo to the project paths it
    declares, as `declared_projects` returns them (the root may be left out; it counts whenever
    a repo declares another path). It only decides whether a repo is drawn nested."""
    graph = graph if graph is not None else units
    index = {unit.id: unit for unit in units}
    ordered = sorted(units, key=lambda unit: (unit.repo, unit.project, unit.id))

    repos = active().repos
    lines = ["flowchart LR"]

    if not units:
        lines.append('    empty["Nothing in flight"]')

    for repo in sorted({unit.repo for unit in units}):
        lines.append(f"    subgraph {repo}")
        in_repo = [u for u in ordered if u.repo == repo]
        declared = set((projects or {}).get(repo, ()))
        # `declared_projects` leaves the root out: a repo declaring another path has it too.
        nested = len({u.project for u in in_repo} | declared | ({"."} if declared else set())) > 1
        current: str | None = None
        for unit in in_repo:
            if nested and unit.project != current:
                if current is not None:
                    lines.append("        end")
                current = unit.project
                lines.append(f'        subgraph {_project_id(repo, current)}["{current}"]')
            state = effective_state(unit, graph, checks_of=checks_of, paused=paused, gated=gated)
            pr = f" · PR #{unit.pr}" if unit.pr else ""
            name = STATES[state].name
            if restacking and unit.id in restacking:
                name = f"restacking onto {restacking[unit.id]}"
            if failed_waiting(unit, graph):
                waits = shown_waits(unit, graph)
                ids = ", ".join(parent.id for parent in waits)
                wait = dependency_wait(waits, merging=merge_parents(unit, waits, graph, repos))
                name = f"{name}, waiting on {ids}, {wait}"
            elif unit.state == PLANNED and (
                merging := merge_parents(unit, waits := shown_waits(unit, graph), graph, repos)
            ):
                name = f"{name}, {dependency_wait(waits, merging=merging)}"
            if wait := second_parent_wait(unit, graph):
                name = f"{name}, {wait}"
            head = f"{unit.id}<br/>{unit.title}<br/>{_carried(unit)}"
            urgency = f" · {note}" if (note := priority_note(unit, graph)) else ""
            waiting = _waiting(unit)
            label = f"{head}<small>{unit.tier} · {name}{waiting}{pr}{urgency}</small>"
            indent = "            " if nested else "        "
            lines.append(f'{indent}{_node_id(unit.id)}["{label}"]')
        if nested:
            lines.append("        end")
        lines.append("    end")

    for unit in ordered:
        for dependency in sorted(shown_dependencies(unit, graph)):
            parent = index.get(dependency)
            if parent is None:
                continue
            if dependency in unit.merge_needs:
                # Thick, and a merge: the `Needs:` line waits for the parent's merge.
                arrow = "==>|needs, merge|"
            elif dependency in unit.needs:
                # Thick: the dependency was written as a `Needs:` line, not inferred.
                arrow = "==>|needs|"
            elif parent.repo == unit.repo:
                arrow = "-->"
            else:
                # Dashed across repos: that edge cannot be stacked, only waited on.
                arrow = "-.->|merge|"
            lines.append(f"    {_node_id(dependency)} {arrow} {_node_id(unit.id)}")

    for state, style in STATES.items():
        painted = f"fill:{style.fill},stroke:{style.stroke},color:{style.text}"
        if style.extra:
            painted += f",{style.extra}"
        lines.append(f"    classDef {state} {painted}")

    for unit in ordered:
        state = effective_state(unit, graph, checks_of=checks_of, paused=paused, gated=gated)
        lines.append(f"    class {_node_id(unit.id)} {state}")

    return "\n".join(lines)


def _pr_url(unit: StoredUnit) -> str:
    """Where this unit's PR lives, asked of the repo's own host - a workspace
    can hold repos on more than one."""
    forge, repo = forges.for_repo(unit.repo)
    return forge.web_url(repo, pr=unit.pr)


def render_markdown(
    units: list[StoredUnit],
    *,
    checks_of: ChecksOf | None = None,
    paused: Collection[str] = (),
    gated: Collection[str] = (),
    restacking: Mapping[str, str] | None = None,
    projects: Mapping[str, Collection[str]] | None = None,
) -> str:
    """The committed page: the diagram, a legend, and what awaits review."""
    shown = in_view(units)
    hidden = len(units) - len(shown)
    awaiting = [unit for unit in units if unit.state == IN_REVIEW]
    awaiting_lines = (
        "\n".join(
            f"- `{unit.id}` ({unit.repo}) — "
            # Absolute: the PR is in the unit's repo, not the planning repo
            # this page is committed to.
            + (f"[#{unit.pr}]({_pr_url(unit)})" if unit.pr else "PR not opened yet")
            for unit in sorted(awaiting, key=lambda u: u.id)
        )
        or "- Nothing is waiting on review."
    )

    diagram = render_mermaid(
        shown,
        graph=units,
        checks_of=checks_of,
        paused=paused,
        gated=gated,
        restacking=restacking,
        projects=projects,
    )
    gate_legend = (
        "\n  A unit may also wait on a held e2e-test split: it is not started until the split\n"
        "  is released, and the round that finds the hold gone starts it."
        if gated
        else ""
    )
    return f"""\
# Unit dependency graph

{_count(len(shown), "unit")} in view across {_count(len({u.repo for u in shown}), "repo")};
{hidden} finished, closed or unplanned not shown. Only unfinished work is drawn, with the merged
units it builds on directly. Rewritten whenever a unit changes state; do not
edit by hand.

```mermaid
{diagram}
```

## Legend

A repo with several projects is drawn with a subgraph for each project that has a unit in
view, titled with the project's path (`.` for the root).

- **planned** — ready to start when a slot and the depth cap allow.
- **blocked** — waiting on a dependency. A cross-repo dependency (dashed
  edge) must *merge* first; a same-repo one must be through its build/review
  loop, so there is a reviewed branch to stack on. A thick edge labelled
  `needs` (`==>`) is a dependency its dependent wrote as a `Needs:` line, not
  one the planner inferred; it releases a planned dependent once the same-repo
  parent is in review, and a failed dependent waits for the merge whatever the label says. An
  edge labelled `needs, merge` is a `Needs:` line that waits for the parent's merge and the next
  tick; a dashed edge labelled `merge` is a cross-repo dependency no `Needs:` line wrote.
  A `Needs:` line the chain already implies draws no edge, and nor does a dependency another
  one reaches. An edge to a unit a replan
  replaced is drawn from the unit that carries its groups now.{gate_legend}
- **running** — in the build/review loop: an agent is working in a worktree,
  or the run is interrupted before an agent step until the usage window allows
  it and the next tick resumes it.
- **paused-rework** — stopped between steps because a unit it depends on
  went back for rework; it restacks and resumes once that unit is through
  review again.
- **in_review** — through the build/review loop; its PR is waiting for human
  review. Dependents in the same repo may stack on it. Deliberately uncapped.
- **checking** — in review, but its checks are still running (or none has
  registered since its push); it reads in-review once they pass.
- **merged** — done, and no longer counted against its stack's depth.
- **satisfied** — its groups needed nothing beyond what was already on the
  branch it built on; no PR of its own, and no longer counted against its
  stack's depth.
- **held** — a reviewer took it over, or the review loop held it itself: needs
  a human, an escalated class or disagreement, or rounds spent with a pushed
  branch and PR; or a merge left it beyond the rebase cap. Nothing automatic
  touches it, but a later merge restacks the depth case.
- **failed** — stopped on something it could not get past; its feedback says
  what. It is retried when someone requeues it, or once by the pipeline when a wait on
  another unit ends.
- **closed** / **unplanned** — stopped, or dropped from the latest plan while
  still on record.

## Waiting on review

{awaiting_lines}

_Generated {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}._
"""


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def write_page(
    units: list[StoredUnit],
    out: Path,
    *,
    checks_of: ChecksOf | None = None,
    paused: Collection[str] = (),
    gated: Collection[str] = (),
    restacking: Mapping[str, str] | None = None,
    projects: Mapping[str, Collection[str]] | None = None,
) -> None:
    """Rewrite the page, keeping the old timestamp when nothing else changed.

    Called on every store write, so without this each tick would leave a
    one-line diff in a committed file for no change at all.
    """
    page = render_markdown(
        units,
        checks_of=checks_of,
        paused=paused,
        gated=gated,
        restacking=restacking,
        projects=projects,
    )
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

    from agent_build_kit.cli.pipeline import gated_units, parked_units
    from agent_build_kit.installation import load_installation
    from agent_build_kit.pipeline.pr_poller import recorded_checks
    from agent_build_kit.pipeline.unit_store import UnitStore
    from agent_build_kit.pipeline.work_graph import declared_projects

    installation = load_installation()
    parser = argparse.ArgumentParser(description="Render the unit dependency graph.")
    parser.add_argument("--store", type=Path, default=installation.state_dir / "units.json")
    parser.add_argument("--out", type=Path, default=installation.graph_page)
    args = parser.parse_args(argv)

    units = UnitStore(args.store).all()
    write_page(
        units,
        args.out,
        checks_of=recorded_checks(installation.state_dir),
        paused=parked_units(installation, units),
        gated=gated_units(installation, units),
        projects=declared_projects(installation.repos),
    )
    print(f"{args.out}: {len(units)} unit(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
