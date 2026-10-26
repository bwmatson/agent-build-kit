## Why

Nothing at plan time compares priorities. The planner prompt never mentions them, the groups it is shown carry a bare `Priority:` line inside the
raw `tasks.md`, the units already in flight are listed without one, and priority is applied only in code after the plan is made. So a more urgent
unit can be planned to depend on a less urgent one, usually because the model chained two groups only because they sit next to each other in
`tasks.md`. The scheduler compensates at run time (a prerequisite takes the urgency of what waits on it), but only once the dependent exists and
only for the ordering of starts: the unit is still blocked until the less urgent work is built.

Two real cases: a priority-3 unit that 112 priority-1 units waited on, and a priority-5 unit that gated a priority-1 chain. In both the edge was
not needed for any code; it was a chain the model drew between neighbouring groups.

## What Changes

- **The planner is shown priorities.** Each group heading in the prompt carries its priority, each in-flight unit is listed with its priority, and
  the prompt states the rule: depend on a unit only for code it introduces; do not make a more urgent unit depend on a less urgent one because the
  groups are adjacent; independent groups are not chained.
- **An avoidable inverted edge is refused.** A plan that makes a unit depend on an unstarted unit that is less urgent than it is refused, unless
  the plan gives a reason for that edge in a new optional per-unit map `needs_less_urgent` (dependency id to a short reason). The refusal names the
  unit, the edge and both priorities and says to drop the edge or give the reason. A plan that never satisfies it fails like any other planning
  failure (recorded attempt, `failing n/3: <reason>`, `abk replan` exits non-zero), and the next attempt's prompt carries the previous refusal.
  An edge to a started or finished unit is not refused: it cannot be removed.
- **A genuine inverted edge promotes the ancestor.** When a less urgent unit that has not started is waited on by a more urgent unit (the plan gave
  a reason, or an author wrote a `Needs:` line), the ancestor takes the urgency of its most urgent waiter, through chains, and a new optional stored
  field `promoted_from` names the waiter. The promotion is recomputed from the unit's own groups and its current waiters at every plan and after
  every linking of `Needs:` lines, so it lapses when the waiter goes away. A started unit is never changed.
- **Authors are warned before planning.** `abk tags <change>` and `abk check` warn (they do not fail) when a group is less urgent than a group that
  depends on it, using the chain the planner draws and the `Needs:` lines.
- **Effective priority is shown.** The graph, `abk status` and `abk tags` show a unit's or group's effective priority and where it comes from.
- **Joins are chosen by logical grouping first, priority second.** The `Joining:` paragraph of the prompt says to join work that belongs together (one
  change, or the same or closely related files or modules) and, among equally good fits, to join the more urgent work first. Priority never
  overrides a better fit and joins no unrelated work; a joined unit still takes its most urgent group's priority. Guidance only: `check_joins` is unchanged.
- **Docs and skill.** The authoring skill says a group should be at least as urgent as any group that depends on it; the architecture and unit
  graph documents and the changelog say what the planner is shown, what is refused and what is promoted.

## Impact

- agent-build-kit: `pipeline/planner.py` (prompt, schema, `parse_plan`, a new `_check_priority_edges`), `pipeline/unit_store.py` (`promoted_from`,
  `upsert`, `set_priority`, a promotion setter), `pipeline/units.py` (a promotion function and a note for the source of a priority),
  `pipeline/work_graph.py` (group inversions), `pipeline/diagram.py`, `cli/pipeline.py` (`plan_all`, the tick, `abk replan`, `abk status`,
  `abk tags`, `abk check`), the documents, the `abk-authoring` skill and the changelog.
- A plan recorded before this change is not made stale by it (the recorded hash is of `tasks.md` alone). Promotion of the edges already stored
  starts at the first tick after the change is built; removing an avoidable edge needs `abk replan <change>` once. The design gives the runbook text.
- No setting is added. No started unit, branch or pull request is touched.
- Priority 0: waiting units are blocked for as long as the less urgent unit takes, and the cases seen held over a hundred urgent units; it is set to the emergency lane so it starts ahead of the priority-1 queue it is meant to untangle.
