# Design

## What was checked, and where

Read-only against the agent-build-kit checkout; paths are under `src/agent_build_kit/`.

- The guard is `pipeline/planner.py` `_check_groups`: a group in `built` cannot be claimed, a group cannot be claimed twice or also carried by a join, and
  every unbuilt group must be claimed. `built` is assembled in `plan_all` (`cli/pipeline.py`) from the groups of units in `_STARTED` (in flight, failed,
  held, merged, satisfied) and of other changes' planned units that carry this change's groups. The refusal exists to keep three things: no rebuilding of
  work already in main, no two branches building one group, and a failed or held unit keeping its branch, pull request and commits for a person.
- The prompt (`PROMPT` in `planner.py`) says every group must be claimed by exactly one unit and `build_prompt` sends the change's whole `tasks.md`. The
  only sign that started groups are to be left out is `_in_flight_line`'s `builds <groups>` on a started unit, with a comment that the planner has to see
  it. There is no explicit rule, and the stated rule contradicts the hint.
- A unit's agent reads the change's `tasks.md` at each run (the prompts in `pipeline/stack_runner.py` tell it to read it before it starts), so a requeued
  unit sees edited group text with no plan involved. The hash decides only whether to call the planner (`_plan_is_current` in `cli/pipeline.py`).
- `StoredUnit` (`pipeline/unit_store.py`) has `repo` and `tier` (from `Unit`) and a `flag`, the flag of the first flagged group it carries, so all three
  can be compared with the group's tags now.
- `record_plans` writes the plan record under a lock; `_plan_state` renders it for the bare `abk replan` listing; `PlanResult` has the statuses
  `planned`, `failed`, `refused`, `skipped`. Existing tests this extends: `tests/pipeline/test_planner.py`
  (`test_a_built_group_cannot_be_silently_rebuilt`) and `tests/cli/test_replan_*.py`.

UNVERIFIED: how `_needs_planning` (the usage guard's question of whether a round has planning to do) will treat a change whose only remaining work is
the record-only step; the builder confirms that such a change does not count as a model call there. The docs the group touches are `docs/architecture.md`
and `docs/cli.md`; there is no `docs/pipeline.md` in the checkout, so the planning paragraph is in `docs/architecture.md`.

## Nothing left to plan

After the hash check and the tag validation, `plan_all` works out the change's unclaimed groups: groups not in `built` and not carried by an unstarted unit
of another change. When there are none it records the hash as planned (`ok`, no attempts), makes no call, logs that every group belongs to a started
unit that reads the edit at its next step, and returns `planned` so `abk replan` reports it as a success. A tick after the edit therefore makes no call.
Changing a started group's text is safe because the unit never copied the text; only its tags were copied.

## Tags changed under a started unit

In the same step the stored repo, tier and flag of each started unit are compared with the tags of the groups it carries. A difference is printed with
the unit and the way out ("`<unit>` is failed and its group 3 is now [tier1]; `abk requeue --restart <unit>` rebuilds it from the new tags, or restore
the tag") and the record is not written as done, so the report repeats until it is resolved. The unit is never rewritten behind its branch: only
`requeue --restart`, which exists, starts it over. This case is a `refused`-like outcome with its own reason, not a model call.

## Some groups remain

When groups of the change are unclaimed the planner is called as today, with two additions. The prompt states that groups marked built below are taken,
that they must not be claimed, and that no unit is returned for them; dependencies on the units that build them stay valid. The change text sent to the
planner marks each taken group's heading `(built by <unit id>)`. Only the text sent changes; `tasks.md` is not edited. `_check_groups` is unchanged and
still refuses a plan that claims a built group, so a planner that ignores the rule rebuilds nothing.

## Renumbering and deletion

Renumbering or deleting a group a started unit carries is the unsafe case: the unit's branch and the groups no longer agree. It stays refused with
today's message, with no automatic handling.

## Evidence of a refusal

A refused plan stores, in the plan record, the unit ids the planner returned and the refusal reason (not the model's full text). `_plan_state` or the
listing built on it shows the reason, so a bare `abk replan` says why a change is failing.

## Tests, and no tier 2

Everything here is decided by files, the store and a planner reply; the planner is faked at its boundary in tier 1, as in the existing planning tests.
The change touches nothing that needs the live stack, so no group is `tier2`, and `tasks.md` opts out of acceptance with a reason.

## Not included

Applying a tag change to a started unit automatically, and a dry run of a replan, are left out.
