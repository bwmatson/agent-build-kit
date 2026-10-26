## Context

Written against agent-build-kit `origin/main` (`f9f53b4c`); line numbers were re-read there.

`plan_round` (planner.py 1065) asks a model and returns `parse_plan`'s `Plan` (111-215). `plan_all` (cli/pipeline.py 3249) passes the units on to
`_drop_cycle_edges` (3398) and `UnitStore.upsert` (3460), which merges by id: a plan unit with a stored id rewrites that unit; a stored unstarted unit
of the change the plan omits becomes `unplanned`. So the id is the only thing that decides "same unit" across replans, and the model chooses it.
Joins (`check_joins`, joins.py 50-200) name stored units in `onto` and `unit` and refuse one that names a unit of the change being planned
("the plan replaces" it), so a join never holds a plan unit's id.

## The rule

A new module `pipeline/unit_ids.py` holds `assign_unit_ids(units, *, stored, retired, highest_group) -> tuple[Unit, ...]`, pure. `parse_plan` calls it at
the end (before `return Plan(...)`, 215), after every check, so a refusal still cites the model's labels. `stored` is `context.stored` (empty when
`parse_plan` has no context), `retired` the existing parameter, `highest_group` the largest group number of `tasks.md`.

A stored unit is **reusable** when its state is `planned` or `unplanned`, `has_work` is false and it is not `retired`: exactly what `upsert` rewrites or
revives in place. Every other stored id is **taken**: started, `merged`, `closed`, `satisfied`, `retired`, `unplanned` with work.

For each plan unit `U` of change `c` with own groups `G` (`Unit.groups`; joined groups are other changes' and never count), in ascending `min(G)`:

1. **Reuse.** A reusable stored unit of `c` whose own groups equal `G` and that no earlier plan unit took: `U` gets its id. The lowest `(number, id)`
   wins if there are two. Done for all units first, so a later unit's computed id cannot take an id an exact match is owed.
2. **Rule.** Otherwise `<c>/<min(G)>` if free: not in `retired`, not assigned in this reply, and either unknown to the store or the id of a reusable
   stored unit nothing matched (the plan rewrites it, as it does today; that is how a split leaves the lower id with the piece holding the lowest group).
3. **Fallback.** Otherwise `<c>/<m>`, `m` the smallest integer above the highest group number and above the leading integer of every stored id of `c`
   (`3-s1` counts as 3) that is free by rule 2's test. Deterministic: the same store and reply give the same id.

A unit with no group of its own change (only when `parse_plan` had no `groups`) keeps its label and is checked as in rule 2.
Then every `depends_on` entry equal to a label becomes that unit's assigned id (order kept, de-duplicated); an entry that is not a label names a stored
unit and is left. `needs_less_urgent` is read and checked by label inside `parse_plan` and is not stored, so nothing is rewritten; `joins` are left as
they are (above).

Labels: any non-empty string, unique in the reply (the duplicate check at 169 stays, now a duplicate-label check). A label equal to the id of a **taken**
stored unit, retired included, is refused, naming it (replacing the retired-only test at 166): `_check_priority_edges` skips a target that has started,
and `depends_on` would be read as the plan unit where the model meant the stored one. A label equal to a reusable stored id is the old form and is
accepted; it shadows that stored unit within the reply, as a plan unit does today.

**When the id is fixed.** At the first plan that contains the unit, or at the replan that rebuilds it while unstarted (reuse keeps it). A join that later
gives an unstarted unit lower-numbered groups does not renumber it; the join keeps `onto`'s id by design. A started unit never gets a new id.

## Why an integer fallback, not `.k`

Every reader of the last id segment was audited on `origin/main`: `unit_number` (units.py 639, `int(...)`, which also orders `earlier_units`, 644-660),
`unit_transcript_files` and `read_transcripts` (transcript.py 155, 179: `int(number)`), `_run_name` (serve/server.py 198: `int(number)`), the file prefix
`{change}-{n:02d}-` of run logs and transcripts (run_log.py 66, transcript.py 70) with their patterns `\d{2,}` (run_log.py 30, transcript.py 197). A
suffix such as `.2` or a letter fails `int()` in four places and must be added to three file patterns. The places that only flatten an id are safe for
any text: `branch_name` (units.py 217), the lease file (`replace("/", "--")`, lease.py 59), the diagram node (`[^A-Za-z0-9]` to `_`, diagram.py 69) and the
worktree path (workspaces.py 133). An integer needs no parser change. Its cost is order: a fallback unit sorts after the units numbered before it, so
`earlier_units` may not place it before an acceptance or narrow unit numbered between; the planner prompt already makes those units depend on every other
unit of the change explicitly, which is the edge that matters. The fallback is rare for a new change (ids equal group numbers, which are never reused)
and routine only in a change whose old ids were counted by the model.

## Composition

- **a-replaced-unit-points-to-its-successor** (unbuilt): `superseded_by` stays for a real regroup (a join or a split changes the group set) and for the
  one-time case of a stored unit whose group set matches no plan unit; reuse keeps that case small. Its text is narrowed by this change's companion
  edit. Either can be built first; each stands alone.
- **a-dropped-parent-does-not-hold-its-child**: unchanged; still needed for work that is dropped, not renumbered.
- **a-started-unit-keeps-its-groups** (built): the retired-id refusal of its spec becomes the label guard here for the same ids; `GroupOwned` is untouched.
- **a-unit-over-its-tier-is-held-and-split** (unbuilt): its pieces are named `<parent>-s<k>` and checked by its own `_check_split_shape`. A plan made for a
  split request is not renamed: that change passes the flag, and until it exists nothing is skipped.
- No `Needs:`: each of these changes builds on the main branch; where lines overlap a rebase resolves it.
