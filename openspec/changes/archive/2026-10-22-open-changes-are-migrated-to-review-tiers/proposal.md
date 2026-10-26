# Proposal

## Why

A change is planned once and again only when its `tasks.md` hash changes. The ceilings and the review policy are not in that hash
today, and once the sizing change makes them part of the plan record they mark every open plan stale, but nothing acts on it: every
open change stays planned as 750-line units with no review tier, and the work already queued gets none of what the rest of this
series builds. Acting on it is a planner call per change, and the existing `abk replan` reports only how many calls it will make,
then applies whatever comes back: units are reshaped, and any unit the new plan drops silently becomes `unplanned`. A person cannot
see what a migration would do before it does it, cannot do it a few changes at a time in the order that matters, and the old
`[unit-test]` and `[e2e-test]` tags in open `tasks.md` files stay until someone edits each by hand.

## What Changes

- **Stale plans are found and shown.** A plan made under other ceilings or another `review:` section than the ones now in force is
  stale. `abk status`, the `abk replan` listing and the tick say so. A tick does not replan a plan for being stale: only a person's
  command spends those calls.
- **`abk replan --report` is read-only and makes no model call.** For each change it shows the plan state, how many units have
  started and how many have not, and the planner calls a replan would cost.
- **`abk replan --dry-run` asks the planner and writes nothing.** It prints what each change's units would become: the unit ids,
  the review tier expected, the estimated lines against that tier's ceiling, the joins, the started units left alone and the units
  that would be dropped to `unplanned`.
- **Only unstarted work is replanned.** A started unit keeps its shape, and a refused plan keeps the old plan and is reported with
  its reason.
- **Drops are listed before they act.** A replan that would demote a unit to `unplanned` applies nothing for that change until
  `--accept-unplanned` says a person has read the list.
- **Migration is by priority, a few changes at a time.** `abk replan --stale --limit N` takes the most urgent stale changes first and
  honours the planner's attempt and wait handling.
- **`abk tags --fix` rewrites the old test-kind tags** in open `tasks.md` files to `[unit-test]` and `[e2e-test]` by a text edit that
  changes nothing else, and refuses, writing nothing, when it cannot. It is a command a person runs; the pipeline never edits a
  `tasks.md`.
- **The `abk-authoring` skill is brought in line with the new ceilings:** groups no longer need splitting to dodge a 750-line ceiling,
  and each says what it touches so a review tier can be estimated.

## Impact

No behaviour changes until a person runs one of the new options. `abk replan` without them behaves as before except that a drop to
`unplanned` now needs `--accept-unplanned`; a script that relied on the silent drop must pass it. `abk status` gains a line per stale
plan, and `abk tags` gains `--fix`. Rollback of a migration is `abk replan` under the old ceilings.
