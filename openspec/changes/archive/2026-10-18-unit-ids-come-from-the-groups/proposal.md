## Why

A unit id is `<change>/<n>`, and the planner model chooses `<n>`. The prompt's reply shape is `{"units": [{"id": "<change>/<n>", ...}], "joins": [...]}`
(`planner.py` 769-774) and `parse_plan` (111-215) refuses only a duplicate id (169) or a retired one (166). Nothing ties an id to the groups the unit
builds, so the same work gets a different id each time the model counts differently:

- `tier2-tests-are-tagged-by-runtime/5` carried group 6; after a replan `/12` carried group 6 again.
- `plans-do-not-make-urgent-units-wait-on-less-urgent-ones/2` carried groups 3 and 4; after a replan `/4` carried groups 3 and 4 again.
- `a-standing-cause-survives-replans-and-no-cause-changes` had `/2` for groups 1-2 and `/4` for groups 3-4.

That is renumbering, not a change of the work. The old unit goes `unplanned` (`UnitStore.upsert`, `unit_store.py` 740-745) and every stored reference by
id goes stale: a started unit's `depends_on`, `waited_on`, the in-flight lines. It caused a real loop: `a-runtimes-provider-has-usage-windows/5` bounced
about twelve times because its stored `depends_on` held the unplanned `tier2-tests-are-tagged-by-runtime/5`. `a-replaced-unit-points-to-its-successor`
repairs the references after the fact; this change stops making most of them.

The stable identity of the work is `(change, group)`. The program, not the model, should name a unit from it.

## What Changes

- **The program assigns the id.** After `parse_plan` has checked a reply, each unit of the change being planned is given `<change>/<L>`, `L` the lowest
  group number it carries from its own change (joined groups of other changes do not count). The model's `id` becomes a local label, used only to write
  `depends_on` and `needs_less_urgent` inside one reply; the code maps labels to assigned ids and rewrites `depends_on`. The old `<change>/<n>` form is
  still accepted as a label. The prompt says so.
- **No churn.** A planned unit whose own group set equals that of a stored unstarted unit of the change keeps that unit's id, whatever the number, so the
  release renumbers nothing that already exists. A started unit is never renamed.
- **A taken id is not reused for other work.** When `<change>/<L>` is a retired, started or finished unit's id, or is claimed by another unit of the same
  reply, the unit takes the smallest free integer above every number the change has used. A plain integer, because several readers take the last segment
  of an id as one.
- **A label cannot be a taken id**: one that is the id of a retired or started stored unit is refused, so a reference cannot silently mean the wrong unit.
- No change to joins (they name stored units only), to `Unit`, to the store format or to branch names.

## Impact

- agent-build-kit: new `pipeline/unit_ids.py`; `pipeline/planner.py` (`parse_plan`, the prompt); `docs/architecture.md`, `docs/unit-graph.md`, the
  `abk-authoring` skill and the changelog. `cli/pipeline.py` needs no edit: it takes the plan's units as returned.
- Composition (design.md): `a-replaced-unit-points-to-its-successor` stays for real regroups and the one-time legacy case and is narrowed by a second
  change; `a-dropped-parent-does-not-hold-its-child` and `a-started-unit-keeps-its-groups` are unchanged. No `Needs:` on any of them: the overlap is
  textual, and each builds on the main branch alone.
- Priority 0: the loop above is live, and every replan that renumbers makes a new one possible.
