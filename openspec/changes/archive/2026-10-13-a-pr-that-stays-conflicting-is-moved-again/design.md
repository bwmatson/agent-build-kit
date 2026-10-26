# Design

## What was checked, and where

Read-only: `git fetch`, then `git show origin/main:<path>` in the build tool's checkout (origin/main at `7e04c86`). Paths are under
`src/agent_build_kit/`; line numbers are approximate to a few lines.

- **The poll** (`pipeline/pr_poller.py`, `poll` ~195-280). Each open PR is snapshotted (`snapshot`, ~94: `state`, comment ids,
  `review_decision`, labels, `checks`, `head`, `mergeable`). `head` there is the head *branch name* (`pull.head`), not a commit; the
  pull request model (`forges/base.py` `PullRequest`) has `base` as a branch name, no commit of either. At ~235: `if
  current["mergeable"] is None and number in known: current["mergeable"] = known[number].get("mergeable")` — the last definite answer
  stands through an undetermined one. A fresh state file only records (`first_run`); a PR not in `known` goes to `_dispatch_terminal`
  (~290), which dispatches `rework` with `ReworkKind.CONFLICT` when `current["mergeable"] is False` (~307); a known one goes to
  `_dispatch_changes`, whose conflict test is `after["mergeable"] is False and before.get("mergeable") is not False` (~430). A dispatch
  that returns `False` keeps the old snapshot so the event is reported again. The first-sight and transition paths are as the plan says.
- **The only other reader of the answer** is `unmergeable(path)` (~55), called from `cmd_status` (`cli/pipeline.py` ~652) to print
  ` — cannot be merged`. Confirmed with a grep: no other caller in `src/`.
- **What a conflict rework does** (`pipeline/events.py` `on_rework` ~1109, `_feedback` ~1280, `_requeue` ~1300): a held unit does not take
  it (`_not_for_now` returns False, the event comes again); a unit with a thread is resumed (`resume(..., "rework", ...)`); otherwise it is
  requeued `planned` with cause `rework` and feedback saying the branch has been moved onto its base at the start of the run. There is no
  attempt counter on this path: nothing bounds how often it fires except the transition rule that this change replaces.
- **Counters that exist.** `StoredUnit` (`pipeline/unit_store.py` ~164) keeps `pushed` and `pushed_at`, `check_rerun_head` and
  `check_reruns` (the pattern copied here: a count tied to a commit, reset when it moves, bounded by a limit, `on_rerun_checks` ~1190),
  `parked_attempts` and `service_attempts`. `limits.max_review_rounds` (`config.py` 403, default 3) bounds review rounds inside a run
  (`graph/nodes.py` ~1303); nothing bounds conflict attempts.
- **The restack flow** (`pipeline/events.py` `release_children` ~255, `build_restack` ~1354 and its inner `restack` ~1405): called with
  `branch`, `old_base`, `new_base`, `child`, `parent`; it retargets the PR, adopts a moved host head, moves with `resolved_move` and,
  for an unchanged approved diff, runs tier 1 and pushes with the lease; anything else leaves the unit `planned` with
  `restack_deferred`; a conflict the first rungs cannot settle leaves `restack_conflict` (~1541). `move_branch_onto`
  (`pipeline/restack.py` ~330) takes `new_base`, `old_base`, `resolve`, `context`, `must_keep`, `turn`. It is reached only from the
  parent-left-review handlers; a trunk-based unit has no parent, which is the gap.
- **Held states.** `HeldBy` has `NONE`, `REVIEWER`, `REVIEW`, `DEPTH`, `TOOLCHAIN`; `held_for_its_own_reason` treats the review loop as
  a hold the label's removal does not undo.
- **Docs read:** `docs/architecture.md`, `docs/unit-graph.md`, `docs/cli.md`, the `abk-pipeline` skill, the `pr-polling` and
  `restack-conflicts` specs.

## Discrepancies with the plan

1. The snapshot's `head` is a branch name, so it cannot be "the head the conflict was handled at". The unit's own `pushed` (a commit) is
   the head, and there is no base commit anywhere in the pull request model: the base tip is read from the repository by the handler.
2. `mergeable` is kept as the last definite value, but with no time. "Its own latest push is older than the answer" is therefore not
   decidable today; the snapshot gains the time of the poll that read the answer (`mergeable_at`).
3. There is no existing counter for conflict attempts. The plan's "reuse any attempt counter" finds only `check_reruns`'s pattern and
   `max_review_rounds`; the limit is reused, the counter is new.
4. The first-sight path and the transition path send a rework, not a stack move, and their requirement's scenario says "rebased and
   re-reviewed". They keep doing so; the stack move is the first answer only to a conflict that stands (below).

## Decisions

### 1. The poller reports a state; the handler decides

The poller has no store and no repository, so it cannot know a unit's push time or the base tip. It dispatches a `conflict` event, with
the answer's time, for every poll that reads a definite `false`, and the handler (`on_conflict` in `events.py`, beside `on_rework`)
compares and returns `True` (consumed, nothing to do) or `False` (kept: the unit is busy, held for another reason, or paused). Cost per
poll: one store read and, for a unit in review with a fresh answer, one read of the base's tip. Nothing is dispatched for a `false`
that the transition or first-sight path dispatched on the same poll, which is the only place those two paths now overlap: they record
the attempt too, so the same poll does not start a second.

**Freshness.** Snapshot fields `mergeable_at` (UTC time of the poll that read the last definite answer) and `conflict_since` (the
first such poll of the current run of `false` answers; cleared by a definite `true`). The existing keep-last-definite behaviour is
unchanged: it still stops one conflict from reading as two. A conflict is *fresh* when `mergeable_at > unit.pushed_at`. A snapshot
with no `mergeable_at` is never fresh, so an upgrade dispatches nothing from old data; the first definite read after it decides.
Clock: both times are the build tool's own UTC clock (`pushed_at` is recorded when the push is; `mergeable_at` when the poll runs).
UNVERIFIED: that the host never reports a stale definite answer shortly after a push (it reports undetermined, per the existing
comment at ~236); if it did, one wasted attempt would follow, bounded by the rules below.

### 2. What is remembered, and the rule

On `StoredUnit`: `conflict_tip` (the base tip at the last attempt), `conflict_head` (the unit's `pushed` when it started),
`conflict_attempts` (attempts at that tip), `conflict_at` (when it started). The rule, in order, for a unit in review with a fresh
definite `false`:

1. No recorded tip, or `conflict_since` later than `conflict_at` (a definite `true` came between): episode start, attempts 0.
2. Tip differs from `conflict_tip`: new base, attempts 0, attempt made.
3. Same tip, `pushed` differs from `conflict_head` and the answer is later than `conflict_at`: the last attempt pushed a head and the host
   still conflicts. If `conflict_attempts < max_review_rounds` another attempt is made; else the unit is held (decision 4).
4. Same tip, same `pushed`, answer later than `conflict_at` and the unit is back in review: the last attempt changed nothing. The
   unit is held at once. Dispatching again would repeat it.
5. Same tip and same head with the answer not later than `conflict_at`: nothing; the attempt may still be running.

The stored `mergeable` is read for nothing in this rule. The transition and first-sight dispatches go through the same record, so a
conflict they send is attempt one at its tip.

### 3. Restack first, rework second, and which the poller dispatches

An attempt is one of two things the repository already has.

- **The stack move** for a unit whose base is the trunk (`base_of` names the trunk; UNVERIFIED that it names it rather than a branch
  for a unit with no parent) and which has no thread parked in review: the existing `restack` callable with the unit's recorded base as
  `old_base` and the trunk tip as `new_base`. It retargets nothing (same base), adopts a moved host head, moves with the scoped
  resolver and rerere, and finishes as the merge handler's restack does. It is mechanical, costs no build slot and no review round when
  clean, and is what a person would do. It needs a `parent` for the resolver's intent text; with no parent the handler passes the unit
  itself, UNVERIFIED (the plan's `predecessor` for a trunk base is not read).
- **The conflict rework** (`on_rework` with `ReworkKind.CONFLICT`) for every other case: a first attempt from the transition or
  first-sight paths; a second attempt at one tip; a stacked unit; a unit with a thread; a stack move that ends `restack_conflict`.

Why the first-sight and transition paths keep the rework: their requirement states it and other scenarios depend on it; changing them
would also change the number of agent runs per conflict for units the problem does not touch. The stack move is only for the case this
change adds, where the previous attempt has already shown the conflict recurs.

### 4. The bound and the stop

`limits.max_review_rounds` (default 3) is reused, as the most attempts at one base tip: a conflict an agent cannot resolve in as many
rounds as it is allowed to fix a review is not one it will resolve in a fourth. No new setting. The count restarts at each base tip,
so a trunk that keeps moving is followed one attempt per move and each is a real external change, not a loop; the total is not bounded
and need not be. When the bound is reached, or an attempt changed nothing (rule 4), the unit is held, `held_by` the review loop (the hold
that a reviewer's label removal does not undo, and that `abk release` frees), with a note such as `conflicts with main since 14:50 UTC:
moved 3 times at <tip>, the host still reports a conflict` or `... the last move changed nothing`. Failed was considered and rejected: the
work is sound, a person only has to settle a conflict.

**The rework that changes nothing.** In the observed case the agent found the base already merged. The rework run ended and the unit
returned to review with the same `pushed`. By rule 4 the next fresh definite answer finds same tip and same head and holds the unit
with that reason. The stored `mergeable` has no part in it. UNVERIFIED: that a conflict rework which changes nothing always returns the
unit to review rather than leaving it `planned` or `failed`; the test for it is written first and fixes the spec if it does not.

### 5. Usage limits, the turn and the claim

The handler takes the unit's claim (the branch lock) for the stack move, as the merge handler does; `BranchBusy` returns `False` and
records no attempt. The stack move holds the repository's turn per phase, as `a-conflict-is-resolved-in-one-session-without-holding-the-repo-lock`
specifies; the handler adds no turn. A pause: the handler asks the pause marker (`pause_in_force`) and the usage gate before the
resolver, as the stack move's own callable does once the lane sibling lands (today `claude_resolver` has no gate and relies on the pass
guard and the runtime's refusal, and a refusal already leaves the unit `restack_deferred`). A clean move is not gated. A move deferred
by a pause is not an attempt: `conflict_attempts` is incremented only when the move ends in a push, a resolved plan, or a rework.
The rework path is a requeue, and the pass's own guard governs the run.

### 6. Status

`cmd_status` prints for a unit in review with a conflict (the answer is `false`, from the snapshot's `conflict_since` and the unit's
`conflict_attempts`/`conflict_tip`): `conflicts with <base> since <time>; moved N times`, then one of: `the next poll moves it`, `its
branch is being built`, `waiting for the usage pause to end`, or, for a held unit, the hold's note. The existing ` — cannot be merged`
mark stays for an entry with no conflict data (a snapshot from before). The graph page is unchanged.

## Relation to the pending changes

- `a-restack-takes-no-slot-and-runs-when-seen`: the handler calls the same `restack` callable the merge handlers do. If the lane lands,
  the callable hands the move to the lane and the handler records the attempt when it is handed over; if it does not, the move runs
  inline in the poll as the merge handler's does (so one conflicted unit holds the rest of the poll, as it does there). No `Needs:`: this
  change edits `build_stack_moves`'s binding and adds a caller; nothing the lane creates is required to write it.
- `a-conflict-is-resolved-in-one-session-without-holding-the-repo-lock`: the one-session step and per-phase turn improve what the stack
  move costs and are used as they appear; the handler's claim and the absence of its own turn do not depend on them.
- `a-moved-base-is-checked-by-what-it-can-affect`: the clean move's tier 1 is chosen by the scope rule once that change lands; this change
  does not choose it.

None of the three is required, so there is no `Needs:` line.

## Risks

- A busy trunk costs an attempt per move: one stack move when clean, so the cost is a rebase and a tier 1 run.
- A hold on rule 4 stops a unit whose conflict a later trunk move would have cleared. A person releases it; the alternative, waiting
  silently, is the bug.
- UNVERIFIED items above: trunk `base_of`, `parent` for a trunk-based restack, a no-change rework's end state, the host's stale answers.
