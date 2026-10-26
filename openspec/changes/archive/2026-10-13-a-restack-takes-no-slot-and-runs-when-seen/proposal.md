# Proposal

## Why

A base that moves today costs a unit a place in a queue it should not be in. The measured cost (the ledger and run logs of the installation
this was drawn from: 45 `base_changed` events over 196 units; `queue_full` waits averaging 39 minutes and `slot` waits 19) is mostly
latency, not git:

- **A restack is made to wait for a build slot.** A unit in review whose parent merged is told its base moved; that parks its thread
  `running` with cause `base_changed`, and the tick resumes it at `prepare` in one of the `max_concurrent_stacks` workers. A unit a run
  held for a moved base is `planned` and waits for a worker the same way. The move itself takes seconds; the wait for a worker is the
  cost, and it is paid by a restack that does no building.
- **A restack is made to wait for the next look.** A unit left `planned` with cause `restack_deferred` or `restack_conflict`, or held
  for a second moved base in one run, is not readmitted by a running pass (`READMITTED_CAUSES` holds only `rework` and `base_changed`);
  it waits for the next tick and then for a worker.
- **A conflicting restack blocks the poll.** The merge handler restacks each child inline, under the unit's claim, so one conflicted child
  holds up the rest of that poll, and the pass's own refresh (`_refresh`), for as long as the resolver runs.

The person who asked for this put it plainly: restacks should not take a slot at all and should be resolved as soon as they are seen. And
a correction to an earlier draft: restacks do need to honour the current usage limits. Both are in this change.

## What changes

- **A lane for restacks.** Restack work is run by its own small pool of workers, sized by `limits.max_concurrent_restacks` (default 2, a
  positive integer, checked at load). It is outside the build workers, so a restack never takes a build slot and a busy pool never delays
  one. A unit that is already in progress is not admitted again: the restack is not a start.
- **Started when seen.** The merge handler hands a moved child to the lane instead of restacking it inline; a scan after every poll, every
  finished unit and every usage pause hands it units whose branch no longer holds their base. Nothing waits for a tick or a free worker.
  Queued restacks run in the order they were seen.
- **Usage honoured as for any agent run.** The lane asks the same guard, with the same thresholds and the same estimate when a read is
  refused, before the resolver step; a clean move runs no agent and is not gated.
- **Shown.** `abk status` and the graph say `restacking onto <base>` and the status gains `restacks: N running, M waiting`. A restack is
  not a build: the slot gauge (`free_workers`) is unchanged by it.
- **Unchanged.** A unit whose step is running is not restacked under it; the run stops at its next boundary, as now. A run that finds a
  second moved base in one run still holds the unit `planned`. The repository's turn is taken per phase, as the sibling change
  `a-conflict-is-resolved-in-one-session-without-holding-the-repo-lock` specifies.

## Impact

- Capabilities: `unit-scheduling` (the lane, the setting, the rule that a restack takes no slot, the counting, the status line) and
  `restack-conflicts` (the usage guard before the resolver in the lane, the unit the lane leaves alone).
- Code: a new `pipeline/restack_lane.py`; `cli/pipeline.py` (`_schedule`, `resumable_units`, `_refresh`, `build_stack_moves`, `cmd_status`);
  `pipeline/events.py` (`release_children`, `on_release`, `reconsider_depth_hold` hand a child to the lane); `config.py`.
- Depends on `a-conflict-is-resolved-in-one-session-without-holding-the-repo-lock` (the one-session step the lane runs and the per-phase
  turn) and `every-agent-call-is-recorded` (the `restack` ledger node).
- No existing setting changes meaning. A new setting is added with a default, so an installation that sets nothing gets the lane at 2.
