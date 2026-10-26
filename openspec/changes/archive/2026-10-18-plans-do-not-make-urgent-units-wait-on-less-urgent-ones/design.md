## Context

Priority is set in code after a plan: `unit_priority` takes the most urgent priority among the groups a unit builds, carried ones included, and
`_set_priorities` stores it for a unit that has not started. Edges come from the planner model; no code chains a change's groups. The prompt says
to depend on a unit for code it needs, for overlapping files or for an API shape, and the `Independent:` line is the one thing that removes the chain
around a group. The plan checks (`_check_groups`, `_check_acceptance`, `_check_independent`, `_check_dependencies`, `check_joins`,
`drop_cycle_edges`) look at no priority. `link_needs` adds author-declared `Needs:` edges every tick with only a cycle check. At run time
`effective_priority` and `waiting_on_me` let a prerequisite start at its waiters' urgency, and a started unit keeps the priority it started with.

A model plan is attempted once per planning pass. A refused attempt is recorded (`attempts`, `reason`, the unit ids) and the next tick plans the
change again until `max_plan_attempts` (3) is used up; `abk replan` plans now and counts attempts from none. Today the reason of a refused attempt
is recorded but is not shown to the model on the next attempt.

## Decisions

- **Show the numbers.** Each group heading in the prompt gets ` (priority N)` beside the existing ` (project <path>)` and ` (built by <unit>)`
  marks, for every group including those at 3, resolved from the group's own line or the change default. Each in-flight line gets `priority N`
  (the stored priority, promotion included). One prompt bullet states the rule. The prompt also says that a unit takes the most urgent priority of
  the groups it builds, so a group is combined with another of a different priority only when they share code.
- **Joins: logical grouping first, priority second.** The `Joining:` paragraph of `PROMPT` is reworded, not extended by a check. Order of the
  guidance: (1) join work that belongs together, groups of one change or of different changes that modify the same or closely related files or
  modules, and never two items merely because both are small; (2) only among candidates that fit equally well, offer the more urgent work its
  partner first, so a less urgent item does not take a partner that a more urgent item with similar files could use; (3) a priority never overrides
  a better fit, and there is no equal-priority rule and no gap limit. A unit keeps taking the most urgent priority of all its groups (`unit_priority`,
  unchanged): the join is an efficiency gain, and the unit must still resolve the most urgent item at that item's priority, so that is not a defect
  to fix. `check_joins` in `pipeline/joins.py` is unchanged; a test on the prompt text and a test that `check_joins` ignores priority cover it.
- **The reason is a per-unit map.** A unit object may carry `needs_less_urgent`: an object whose keys are ids the unit lists in `depends_on` and
  whose values are non-blank strings, the reason in a few words. This mirrors `Independent:`, which also demands a reason, and keeps the reason next
  to the edge it excuses. A key that is not in `depends_on`, a value that is not a non-blank string or a field that is not an object refuses the
  plan with a message naming the unit. A reason for an edge that is not inverted is accepted and ignored. The reason is not stored: the stored trace
  of a genuine edge is the promotion it causes (`promoted_from`) and the edge itself.
- **`_check_priority_edges(units, groups, stored, catalog)`** runs in `parse_plan` after `_check_dependencies`, beside the other group checks. A
  plan unit's priority is the most urgent of the priorities of its groups in `groups`. For each dependency the target is judged by its OWN
  priority: a plan unit from its groups, a stored unit by `unit_priority(stored unit, catalog)` and not by its stored value, which may be a
  promotion and would hide the edge. The edge is refused when the target has not started (a plan unit that is not stored as started, or a stored
  `unstarted` unit), its priority number is larger than the dependent's, and the dependent has no reason for it. An edge to a started, merged,
  closed or satisfied unit is not checked. Without a join context the check sees only the plan's own units. All refused edges are named in the
  message, the first on its first line: `unit app/9 (priority 1) depends on app/5 (priority 3), which is less urgent: drop the edge, or give the
  reason in needs_less_urgent["app/5"]` followed by `(and N more)`. The first line is what the record keeps (300 characters), so it carries the
  whole instruction.
- **Retry and failure.** The refusal is a `PlannerError`, so the existing path applies unchanged: the attempt is recorded with the unit ids and the
  first line, the change is planned again by the next tick, `abk replan` lists `failing 1/3: <reason>`, then `given up`, and `abk replan` exits 1.
  What is new is that the reason is now read back: when the recorded plan has the digest of the current `tasks.md` and a refusal reason, the next
  attempt's prompt ends with `Your previous plan was refused: <reason>. Fix that and answer again.` (this also holds for `abk replan`, whose
  attempt count starts from none but which may still read the reason). Only a refusal by the plan check is fed back, not an outage or a failed
  call. No raw error or traceback reaches the person, and no extra attempt is added.
- **Promotion is recomputed, not accumulated.** `promote_ancestors` works over all stored units. For each unit that has not started: its own
  priority is `unit_priority` from its groups; its waiters are the units `waiting_on_me` finds, with units that are `unplanned` or finished left
  out (a satisfied unit is looked through, as there); a waiter's priority is its stored one if it has started and its own if not (the two agree
  through chains, so this is the fixed point in one pass). The unit's priority is the most urgent of its own and its waiters', and `promoted_from`
  is the waiter that gives it (ties: the id that sorts first) when that is more urgent than its own, else empty. A unit is written only when its
  priority or `promoted_from` differ. A unit that has started is never read as a target: it keeps its priority and its `promoted_from`, and
  `effective_priority` keeps covering the waiters that arrive later.
- **When it runs.** At the end of `plan_all` when any change was planned (so a replan cannot leave a promoted unit below what its waiters need:
  `upsert` writes the plan's default priority and `_set_priorities` the group's own, and promotion then restores it), and after `link_needs` in the
  tick and in `abk replan`. `set_priority` on an unstarted unit clears `promoted_from`, so the own value and the source are never out of step.
- **Lapse.** A waiter that merges, closes, is dropped (`unplanned`) or loses its edge is no longer a waiter at the next pass, so the unit goes back
  to its own priority and its source is cleared, at the next tick or replan, whichever comes first. A unit that started while promoted keeps the
  promoted value and its source, as the rule that a started unit keeps what it started with says.
- **`promoted_from` is a plain optional string field on `StoredUnit`**, empty by default and left out of the record when empty, as the default
  priority is. A store from before reads as empty.
- **Authoring warning.** `inverted_groups(groups, needs)` in `work_graph.py` returns one record for each direct edge where the depended-on group's
  priority number is larger: the edges of `_group_parents` (the chain, `Independent:` groups skipped, `[acceptance]` and `[narrow]` groups after
  every earlier group) and the `Needs:` lines of every group, whose target is read from the other change's `tasks.md`. `_tag_warnings` prints one
  warning for each. The text: `group 5 (priority 3) is needed by group 9 (priority 1): it will be promoted to 1; give it Priority 1 or lower
  group 9` (a `Needs:` target names its change). It warns because the model is only likely to chain as `_group_parents` does; a warning that does
  not happen costs a line, and the fix is the one the prompt already asks for.
- **Display.** `priority_note(unit, graph, excluded)` in `pipeline/units.py` returns the effective priority and its source: the unit's own
  priority, or the stored promotion's `promoted_from`, or the waiter `effective_priority` takes it from. The graph label, the ready-queue line and
  the `priority:` log line of a tick use it; the text for a promoted unit is `priority 1, promoted from app/9`, and `priority 1, from app/9` for a
  started unit covered by a waiter. `abk tags` lists a group as `(priority 3, promoted to 1 by group 9)` when a group that depends on it, directly
  or through a chain, is more urgent.

## Stale plans

The recorded plan is keyed by `plan_digest`, a hash of the specification text of `tasks.md` alone. A change of the planner prompt or schema does
not move it, so no recorded plan becomes stale and the tick does not replan one. This change adds no staleness rule; the change
`open-changes-are-migrated-to-review-tiers` adds a second digest of the policy a plan was made under and `abk replan --stale`, and it is not built
yet. The requirement is therefore stated as behaviour: building this change replans nothing; the first tick after it promotes through the edges
already stored; a person runs `abk replan <change>` for a change whose unstarted units have an avoidable edge, and it replaces only the edges of
unstarted units. If that change is built first, folding a revision of the planner's rules into its policy digest is a decision for it, not for this
one.

Runbook paragraph (for the migration runbook):

> **After the priority rule is built.** Plans recorded before it keep their edges, because a plan is replanned only when `tasks.md` changes or
> `abk replan` is run. Nothing is lost by waiting: at the first tick the unstarted prerequisite of a more urgent unit already takes that unit's
> priority (`abk status` shows `promoted from <unit>`), so the ordering is right at once. What a replan adds is that an edge the planner drew only
> because two groups were adjacent is dropped, or given a reason. Find the changes with a more urgent unit waiting on a less urgent one in
> `abk status`, run `abk replan <change>` for each, a few at a time (each is one model call), and read the result: started units are kept as they
> are, an edge to one is never refused, and a change that cannot satisfy the rule in three attempts shows `failing n/3: <reason>`; fix that by
> giving the less urgent group a priority at least as urgent as its dependents or by lowering the dependent's. `abk tags <change>` lists the
> groups that will be promoted before any model call is made.

## Needs

No `Needs:` between this change's own groups, and none on another change. Four unbuilt changes touch code this one edits, and each overlap is
textual: `a-started-unit-keeps-its-groups` edits the demotion loop of `upsert` and the catch of its refusal in `plan_all` (this change adds
`promoted_from` to the started-unit branch of `upsert` and a call at the end of `plan_all`, independent lines); `a-dropped-unit-parked-on-a-split-takes-no-place`
edits `in_progress`; `units-are-sized-by-review-tier` and `review-policy-and-verdict-recorded-in-shadow` edit the prompt's sizing text and the
schema line (this change adds a bullet and a field, and the schema line is merged by hand in either order). None supplies a function, field or
state this change calls, and the checks read only `unstarted`, `unit_priority`, `waiting_on_me` and the finished states as they are now.

## Risks

- A plan that is correct but needs an inverted edge costs an attempt until the model gives the reason; the feedback line names the field to use.
- Promotion makes the stored priority differ from the groups' for a unit, which anything reading `unit.priority` as the groups' value will see;
  the readers found read it as the scheduling value, which is what promotion is for.
- `_task_catalog` validates every change's `tasks.md`; promotion reads it once per pass, and the tick already reads the same files.
