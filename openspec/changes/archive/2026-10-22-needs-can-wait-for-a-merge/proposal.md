## Why

Observed on 2026-10-21, three times: a fix to the kit's own code merged, and the unit that was waiting for it ran on the old code anyway.

- **A wait that ends at "in review" is the wrong end for such a fix.** `waiting_on` (`src/agent_build_kit/pipeline/units.py:815-858`) releases a
  same-repo dependent once its parent is in `REVIEWED` (in review, merged or satisfied, `units.py:90`); only a parent in another repo must be
  `MERGED` (`units.py:845-852`). `requeue_wait_ended` (`src/agent_build_kit/cli/pipeline.py:2051-2111`) uses the same test for a failed unit that waits
  on a fix (`elif all(parent is not None and parent.state in REVIEWED ...)`, 2090), then `_requeue_ended_wait` (2114-2134) requeues it. So a failed
  dependent resumed when the fix was only in review, on code that did not yet contain the fix.
- **A merge seen mid-tick is not code the tick has.** `cmd_tick` (`cli/pipeline.py:1143-1190`) is one process: the poll in `run_round` marks the
  parent `merged`, and the same process then releases or requeues the dependent. The kit checkout is fast-forwarded after the merge (the
  `~/agent-build-kit` reflog shows `pull: Fast-forward` right after each merge), but Python modules were imported at the start of the tick, which can be
  hours before, so the tick keeps running the old code until it exits. Pulling main at the start of each tick helps the next tick only.
- **The way to ask for "after the merge" does not exist.** `NEEDS_LINE` (`src/agent_build_kit/pipeline/work_graph.py:146-150`) parses a word `merged`
  after the group number into `Need.merged` (`work_graph.py:751-757`), and `merged_needs_warnings` (`work_graph.py:792-801`, printed by `abk tags` and
  `abk check`, `cli/pipeline.py:5578`) warns that it is deprecated and means nothing. `docs/architecture.md:99-107` and the `abk-authoring` skill
  (`src/agent_build_kit/skills/abk-authoring/SKILL.md:128-135`) say the same. An author who needs the merge can only hold the change by hand.

## What Changes

- **Two kinds of edge, `review` and `merge`, with three reasons for `merge`.** A cross-repo edge is always `merge`: a plain `Needs:` to a group of
  another repository is read as `merge` (an info note in `abk tags`) and `link_needs` stores it. An author's `merged` on any `Needs:` is `merge` and binding.
  A **failed** unit's wait on a parent ends at the parent's merge plus the next tick that loads it, whatever the kind and whichever repo the parent is in. A
  planned dependent on a plain same-repo `Needs:` still starts on the parent's branch once the parent is in review. There are no other rules.
- **The planner is untouched.** It writes plain edges, respects an author's `merged` (an author's kind is binding, survives a replan, and the planner cannot
  loosen it), and a planner-chosen merge kind is future work waiting for criteria (see Not in this change).
- **Two kinds of `Needs:`.** The plain line is unchanged: a same-repo dependent starts on the parent's branch once the parent is in review, a
  cross-repo one waits for the merge. The **merge** kind is `Needs: <change> group <n> merged — why`; the word `merged` straight after the group number
  is un-deprecated and takes that meaning. `abk tags` accepts it and no longer warns. `merged` anywhere else in the line stays part of the reason, and a
  merge `Needs:` on a group of the change's own stays the error it is.
- **A merge `Needs:` is met when the parent unit is merged, or satisfied with its work landed, and its merge is in the code the starting tick runs.**
  The second half applies when the parent's repo is the checkout the kit runs from. The tick records, as it starts, a number, its start time and the HEAD
  sha of the kit checkout it loaded; the unit store records, when a unit is seen merged, the merge commit (`forge.merge_commit`, all three forges) and
  the tick number. The merge is in the tick's code when, for a parent in the kit's repository, the merge commit is an ancestor of the recorded HEAD (for any other repository, when the tick is a later one than the one that saw the merge); with no checkout or no merge commit the
  rule falls back to "a later tick than the one that saw the merge". A merge seen by the tick that is running is never in its code, so the dependent
  waits for the next tick.
- **The same test serves every consumer.** `waiting_on` adds the unmet merge parents (also when the chain already implies the dependency), so the
  scheduler, `blocked`, the graph, `abk status`, a requeue parked as `gated` and `requeue_wait_ended` all agree. The wait-end rule for a failed unit
  is "waiting_on is empty", and for a failed unit every edge is a merge edge: its wait ends at the merge plus the next tick, not at in review.
- **Visible.** The wait reads `waiting for <unit> to merge` or `waiting for the next tick to load <unit>'s merge` in the planned line, the
  `failed, waiting on X: unit` line and the pipeline log; the graph draws the edge as `==>|needs, merge|`.
- **`link_needs` records the kind** in a new `merge_needs` mark on the unit (a subset of `needs`, recomputed from `tasks.md` every tick).
- **Existing `merged` lines.** 21 lines in 13 live changes were written with this meaning; all their parents and dependents are already merged, so
  they change nothing. A migration check in the tick log and a test over the planning repo's units make sure none delays a started unit; archived
  changes are never read.
- **Guidance, split.** The `abk-authoring` and `abk-pipeline` skill sources and `docs/architecture.md` carry the generic rule only: a plain `Needs:` for
  ordinary stacked work in one repo; `merged` when the dependent's tests or behaviour need the parent's code in the default branch or an e2e group runs
  against a stack built from it; cross-repo is merge automatically; a fix change a failed unit waits on needs none; three generic example lines. The
  repo-specific rule (a change to this repo's own tick, requeue, wait-end, plan, graph, build, usage or gate code, so a dependent that must run on it writes `merged` because a tick loads the kit's code once at its
  start) goes in agent-build-kit's own `AGENTS.md`, section "Code changes go through the spec process", with one example line and no installation named.

Not changed: how a unit that is already running or in review is treated (a merge `Needs:` added later gates only a start or a requeue), the pipeline-written
`Needs:` lines for flaky-test and pre-existing-failure fixes (they stay plain; their docs wrongly show `merged`), and when the kit checkout is
pulled. The pull is a separate matter and this change is correct whether or not it happens: the sha test only releases a dependent once the merge is
really in the loaded code.

## Not in this change

A merge kind chosen by the planner (a `merge_on` field, prompt rules, validation, a join refusal): the person has no criteria yet, so the planner keeps
producing plain edges. Future work, waiting for criteria. Also not here: forcing `merge` for edges into the kit's own code or for e2e units of a repo
with no `dev_stack`.
