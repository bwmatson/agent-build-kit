## Why

Four started units were parked at their e2e-test step on the held split `acp` on 2026-10-19 (`local-forge/3`, `ui-chat-editing/5`,
`dry-guidance/4`, `abk-web-ui/11`; each `planned`, cause `split_held`, `parked_splits` `["acp"]`). A person edited the `tasks.md` of each so its
group says `Split: claude_code` and its task text asks the agent to convert the tests to Claude (for example local-forge task 3.3), and ran
`abk replan`. The units stay parked, for three reasons that each hold on their own:

- **The release looks at the old split only.** `release_split_held` selects the units `_releasable_split_units` returns, the planned units with
  cause `split_held` whose `parked_holds()` is empty (`src/agent_build_kit/cli/pipeline.py:2073-2113`, `pipeline/e2e_holds.py:170`), and
  `parked_holds` reads `unit.parked_splits`, the splits recorded when the unit parked. They are empty only when `acp` itself is released.
- **The replan cannot reach a started unit.** `UnitStore.upsert` gives a unit that has work (a branch) the split, project and priority it started
  with and drops the fresh plan's value (`pipeline/unit_store.py:734-743`), and a started unit is not in the plan at all (`plan_all` hands the
  planner the started units as context, `cli/pipeline.py:3722-3736`, and when every group is taken it only compares the stored repo, project,
  tier and flag with the tags, `_tag_problems`, `cli/pipeline.py:3501-3558`, which does not read the split). So the stored `unit.split` stays
  `acp` and nothing notices that the group now says `claude_code`.
- **No command ends the park.** `abk requeue` refuses a planned unit (`requeue_refusal`, `cli/pipeline.py:5636-5643`: "only a failed or held
  unit can be requeued"), and a plain resume would not help: the code on the branch still tags the tests for `acp`, so the e2e step would park
  again. The agent has to run again, as a rework, to read the new task text.

## What Changes

- **A pass notices a changed split.** Each pass, after planning and before the release of split-held units, compares each parked unit's stored
  split with the `Split:` of the groups it carries as `tasks.md` reads now. A unit qualifies when it is `planned` with cause `split_held` and a
  non-empty `parked_splits` (the unit `_releasable_split_units` would release, but not in flight), its groups all read as one split, that split
  differs from the stored split, and it is none of the splits the unit is parked on.
- **A qualifying unit is released as a rework, once.** The park ends: the unit is delivered a requeue in rework mode (`RequeueReason.FROM_FAILURE`,
  as `release_gated` delivers a saved rework) carrying an automatic note that says the group's `Split:` changed from X to Y, that the task text
  changed with it and that the agent should read the group's tasks again. `parked_splits`, `parked_sha` and `parked_snapshot` are cleared and the
  stored split becomes Y, so the next pass finds nothing to do. It is logged in the tick log and in the unit's history as a requeue, and the
  unit's wait record in the decisions file closes as a split release's does.
- **A unit the rule does not apply to is untouched.** A unit whose group still says the stored split, one whose group now says a split it is
  parked on (it stays parked), one in flight, and one in another state or cause are not read, changed or written.
- **A new split that is itself held defers the release.** The unit stays parked and `abk status` says its group now says that split and that it
  waits for it; the pass that finds that split released does the rework. The release of the old split does not resume such a unit in the
  meantime, so it never runs its e2e step on tests the plan has moved.
- **`abk status` and `abk replan` show it.** While deferred, the unit's parked line names the new split; once released, the unit is reworking
  and its history says why. `abk replan` runs the same step after it plans, so the person who replans sees the release at once.

No new command, no new state, no new requeue reason, and no change to how a unit parked on a split that is released is resumed.
