# Proposal

## Why

A change whose `tasks.md` is edited is planned again, and the planner is handed the whole file. When the edited group belongs to a unit that has
started (failed, held, in review, merged), nothing is left for the planner to decide, yet the call is made, and it can fail: the planner returned a unit
claiming the group the started unit already builds, and the plan check refused it, as it must. The change then kept a stale hash, so each tick asked
again until the attempts ran out. Editing a failed unit's group to fix its spec, then requeueing the unit, is ordinary, and it hit this dead end twice.

Two causes. The prompt says every group must be claimed by exactly one unit, and shows the whole change; the only hint that started groups are to be
left out is one phrase on an in-flight line, which contradicts the stated rule. And a refused plan leaves no record of what the planner returned, so the
failure cannot be inspected.

## What Changes

- **No planner call when nothing is left to plan.** When every group of the change is claimed by a started unit, the new hash is recorded as planned with
  no model call. The unit's agent reads `tasks.md` live at each run, so a requeued unit sees the edited text.
- **A tag edit on a started group is reported, not applied.** The repo, tier or flag a started unit stored at plan time is compared with its group's
  tags now; a difference is named with the way out (`abk requeue --restart`, or restoring the tag) and the plan is not recorded as done.
- **Renumbering or deleting a started group stays refused**, as today.
- **`abk replan` prints the outcome** for such a change, so a person sees that nothing was asked and why.
- **The planner is told the rule.** The prompt says groups marked as built are taken and never to be claimed, and the change text marks each taken
  group's heading `(built by <unit id>)`. The refusal of a plan that claims one stays as the backstop.
- **A refused plan leaves evidence.** The record keeps the unit ids the planner returned and the refusal reason, and a bare `abk replan` shows it.

## Impact

- agent-build-kit: `plan_all` and the plan record, the planner prompt and the change text it is given, `abk replan`'s listing and output,
  `docs/architecture.md`, `docs/cli.md` and the changelog.
- Spec: `unit-scheduling`, where the replan command's requirements live.
