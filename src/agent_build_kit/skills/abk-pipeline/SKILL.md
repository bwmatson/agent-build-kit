---
name: abk-pipeline
description: TRIGGER — read when asked what the abk pipeline is doing, why a unit or change is stuck, what `held`/`failed`/`in_review` means, or before running `abk tick`, `abk verify` or `abk archive` in a planning repo. SKIP when the question is about writing a change's tasks (abk-authoring) or about abk.yaml and `abk doctor` (abk-config).
version: 1.0.0
generatedBy: agent-build-kit
---

# Reading and driving the abk pipeline

The pipeline runs unattended: a timer calls `abk tick` every few minutes in
the planning repo. Once a tick has work, and before its round, it keeps the
pipeline's environment current: it runs `environment.sync` when the listed
inputs changed, then `environment.check`, and syncs once more if the check
fails. If the check still fails the tick starts nothing and exits 1 with the
check's output, with no unit failed; fix the environment (`abk doctor` runs the
check) and the next tick resumes the units waiting for it. A tick is one pass —
check the usage window, poll GitHub,
plan what is new, verify and archive what has merged, build what is ready —
and every step is idempotent, so running one by hand changes nothing a timer
would not have done.

A pass keeps scheduling until it runs out of ready work: each build that
finishes is followed by a fresh poll and readiness check, so whatever it
unblocked starts in the same pass. A pass can therefore last hours; to see
what the pipeline is doing, watch the pass, not a single unit.

## Commands

| Command | What it does |
|---|---|
| `abk status` | Whether the pipeline is paused, the usage reading, the environment's state (healthy, or unhealthy with the check's output), units by state, which PRs are waiting for a human, any `held` or in-flight `planned` unit with `no recorded cause`, and the ready queue in start order with the reason for each place (priority, or planned order). Never changes anything. |
| `abk graph` | Regenerate the unit graph page (`docs/unit_graph.md`) from `runs/units.json`. |
| `abk tick --dry-run` | Run a tick's reasoning — poll, plan, work out what is ready — and report it without building anything; it does not sync the environment or resume units waiting for it. |
| `abk tick` | A real pass, the same one the timer runs. Safe at any time. `--only <unit>` builds just that unit if it is ready. |
| `abk verify <change>` | Deploy a fully merged change and run its live (tier 2) tests, then archive it; exits 1 if it fails or passes without the change being archived. The tick does this on its own once every unit of a change has merged. |
| `abk check` | `openspec validate --all --strict --json` on the planning repo. |
| `abk tags <change>` / `abk tags --all` | Validate a change's task-group tags (see abk-authoring). |
| `abk archive <change>` | `openspec archive <change> --yes`. |
| `abk openspec -- <args>` | Any other OpenSpec command, in the planning repo. |

## Where the state is

- `runs/units.json` — every unit the planner has produced, with its state,
  branch, PR number, review rounds and history. The file is the truth; the
  graph page is a view of it. Read it; only edit it as described under
  `failed` below. A unit's `run_log` names its latest run's file under
  `runs/unit-logs/` (the state directory): that unit's lines, with the step
  and model in its header and the outcome at the end.
- `docs/unit_graph.md` — the unit graph, regenerated on every state change:
  which unit waits on which, and where each one is.
- `runs/paused.json` — present while the pipeline is paused for usage; says
  until when and why.
- `runs/verified.json` — the outcome of each change's verification.
- `openspec/changes/<change>/` — the change a unit belongs to; its `tasks.md`
  is ticked as units pass review.

## Unit states

A **unit** is one PR's worth of work in exactly one repo, built from one or
more task groups of a change.

| State | Meaning | What to do |
|---|---|---|
| `planned` | In the graph, waiting for its dependencies and a free slot — or a unit held before a step, which its next run decides again from the branch. A pass lets such a unit back in only when it was sent back for rework or its base changed, or when it was parked with the cause `host_unavailable` (the code host could not be reached) and its backoff of 1, 2, 5, 10 then 30 minutes by consecutive parking has elapsed — it then resumes at the failing step, and an approved, pushed unit goes straight to the pull request step; any other cause waits for the next pass, and the tick log names it. A step already running is never interrupted; a usage pause leaves the unit `running` (below), not `planned`. | Nothing. `abk tick --dry-run` says whether it is ready. |
| `running` | A worktree is open and an agent is in the build/review loop, or the run was killed or paused for the usage window and its thread is interrupted. | Nothing. A killed run is resumed at the node it was in by the next tick; a usage pause resumes on the first tick the usage guard allows. Status, the graph and the label may name it `reworking` (answering review or check feedback) or `rebasing` (a conflict or moved base): derived names for a stored `running`. A PR is a draft while its unit is `running` or `planned`. |
| `in_review` | The loop and tier 1 passed; the PR is waiting for a human. | Review the PR. A comment sends it back for rework, and a comment added while that rework runs is addressed by it before it pushes; a merge moves it on. A branch that stops merging into its base sends it back to `planned` by itself; `abk status` marks such an entry `cannot be merged`. It also leaves review for `planned` (read as `paused_rework`) while a predecessor in the same repo is changing its branch, and returns by itself once that predecessor is back in review. |
| `checking` | Shown, never stored: a unit in review whose checks are still running, or that was pushed moments ago with none yet. It counts as in review for scheduling and dependents. `abk status` lists it as `checking`, apart from `awaiting review`. | Wait; it reads `in_review` once its checks pass, or a repo with no checks has waited `limits.checks_register_seconds`. |
| `merged` | Landed. | Nothing; the change archives once every unit is merged and verified. |
| `closed` | The PR was closed without merging. | Units stacked on it are left as they are; re-plan if the work is still wanted. |
| `held` | A reviewer took the unit over, the toolchain cannot build it, the review loop held it itself, a merge left it beyond `limits.stack_depth_rebase_cap` — a change only a human can make, an escalated class or disagreement, or rounds spent with a pushed branch and PR. The pipeline will not touch it (a depth hold is released by a later merge). | See below. |
| `failed` | The build raised. With the cause `environment`, the pipeline's own environment failed its `environment.check` before tier 1; the unit keeps its slot, `abk status` says it is waiting for the environment, and the tick resumes it once the environment is healthy. | See below; for the environment cause, fix the environment (`abk doctor` runs the check). |
| `satisfied` | The unit's groups were already implemented — by an earlier unit that worked ahead of its own plan — so it added no commits of its own, and what was already at the tip passed tier 1. | Nothing; its groups are ticked and its dependents released, the same as a merge: a pull request stacked on it is moved onto its predecessor's branch or the trunk and retargeted before the satisfied unit's own is closed. No PR was opened — or, if a rework found this after one was already open, the reason (the groups, that they were implemented elsewhere, and where when the graph can say) was posted on it and it was closed. |

### `held`

Four ways in: a reviewer put the `agent-hold` label on the PR, the review loop
itself held it, a merge left it deeper than `limits.stack_depth_rebase_cap`
(the history note names the depth and the cap, and the branch it is still on),
or the tick found it cannot build the unit (the unit's `history` entry says
which — a toolchain profile the framework does not implement yet, for
instance).

- A reviewer's hold: the human is driving. Finish the PR by hand, or remove
  the label: the next poll returns the unit to `in_review` (the log says
  `release`), and a comment or failing check left during the hold is then
  delivered as a rework. Removing the label frees only a hold the label made;
  the unit records why it was held (`held_by`: `reviewer`, `review`, `depth` or
  `toolchain`), and the others stay held, the log saying so. A record from
  before the cause was kept is read from its last note. A depth hold the label
  took over (a merge cannot free it while the label is on) goes back to being a
  depth hold when the label comes off, or is restacked from the branch it was
  still on if a merge meanwhile brought it within the cap.
- The review loop's own hold: read the unit's `feedback` and its last
  `history` entry to see which of these it is. A change only a person can
  make (`needs_human`) or a repeated disagreement need a decision on the
  point itself; a problem the reviewer says is an open-ended class needs a
  decision on the approach, not another round; rounds spent with blocking work
  outstanding leaves a pushed branch and a PR carrying the open points, ready
  to finish by hand.
  What a reviewer returns is a verdict: `approved`, a `findings` list (file,
  optional line, summary, consequence, what done looks like, required), and
  from round two an `earlier` list answering each earlier required finding by
  id as `fixed`, `open` or `declined`. The review loop keeps each
  round's findings, ids and the commit it judged in the unit's thread; a required finding, or an
  earlier one left open or unanswered, means the round is not an approval.
- A toolchain hold: nothing a retry fixes. Either build the unit by hand on
  its branch, or change the plan.
- A depth hold: no action needed. Its PR was retargeted, and a later merge in
  the same repo restacks it once its depth is within the cap. To move it
  sooner, raise `limits.stack_depth_rebase_cap` or restack the branch by hand.

### Parked for its worktree

A `held` unit with the cause `dirty_worktree` found uncommitted changes in its
worktree that its own killed agent did not leave: a hand edit, or an edit while
the unit waited. `abk status` lists it as `parked` with the paths. Nothing is
cleaned, since the changes may be the only copy. Commit or remove them, then
`abk requeue <unit>` resumes a park at an agent step at that step, and begins a park anywhere
else again at `prepare`. A requeue while the tree is still dirty leaves it parked. Changes an agent left when it was killed
mid-run are not this: the node resumes over them and commits them.

### Attached to a chat

A `held` unit with the cause `attached` has uncommitted changes in its worktree
that a chat in `abk serve` left, under a lease whose server has since gone. The tick
commits and continues nothing over them. `abk status` lists the unit as `attached`
with the number of files (a chat that is still open is listed too, and the unit is left
alone). Either start `abk serve` again, which takes the lease over so the page can commit or
discard, or run `abk attach release <unit> --commit "MESSAGE"` to commit them or
`abk attach release <unit> --discard` to restore the tree; with neither, a dirty tree is
refused. The command refuses while a step is running on the unit. The unit stays held
afterwards: `abk requeue <unit>` returns it.

### `failed`

The run raised an exception, or its checks failed; its last log line in the
tick output says which, and `abk status` shows the unit. A branch is checked
(lint, types, tests) before a reviewer is asked, and sent back to the builder up
to `limits.max_check_rounds` times (3 by default, counted per review round; `null` for no limit) before it fails with the output kept.

Fix the cause first where it is outside the branch — a missing credential, a
broken toolchain, a branch someone deleted — then `abk requeue <unit>` resumes
it where it stopped. Where the failure is in the branch's own work (a type
error, a failing test) a plain requeue meets the same failure again; use
`abk requeue <unit> --rework` to keep the work and hand the agent the saved
output. `--restart` throws the attempt away. Never edit `runs/units.json` by
hand: a failed unit remembers its step, and putting it back to `planned` alone
sends the next run past the agent to a check on the same branch.

A plan is made when a change's `tasks.md` changes, not on every tick. Run
`abk replan <change>` (or a unit id, `--all`, `--failed`) to plan again now when a
unit waits on a dependency it no longer needs (a `Needs:` line changed in another
change), when a change gave up planning (the tick logs it, and `abk replan` with no selector lists each change's plan state), or when
neighbouring changes' units changed since it was planned. Started work is never
touched; `--forget` only clears the record and leaves the planning to the next tick.

A unit with a `Needs: … merged` line whose dependency has not merged waits instead:
`abk requeue` leaves it `planned` with the cause `gated` (shown by `abk status` as
waiting), and the tick resumes it in the requeued mode once the dependency merges.

A test that failed under load and passed twice alone is a flake, not a failure: the unit is
parked the same way (`gated`, its note names the test) with a `Needs:` line on the one
change the pipeline wrote to fix that test. `abk status` lists each flaky test as `flaky:`
with its count and fix change; the unit resumes at tier 1 once that change merges.

### What an agent may run on the code host

Only to read its own pull request, by the commands its repo's forge declares
(`gh pr view` on GitHub, `az repos pr show` on Azure DevOps). Merging, voting
and the raw API escapes are refused on every repo, whatever its forge. On Azure
DevOps, stacked pull requests are unsupported and units serialise per repo.

### Labels on the pull request

Two families. The `agent-` labels are instructions a person sets:
`agent-hold` (the unit is taken over; it stays until a person removes it) and
`agent-rework` (send it back; the pipeline **removes it once acted on**, so it
can be given again). The other family is the pipeline's own: one **state label** per pull
request, replaced whenever the unit's state changes, and a **change label** for each change it carries. State names and colours (the outline) are the graph's, so
a label reads as its node does. `merged`, `closed`, `unplanned` and
`satisfied` have none: the host shows the first two, the last two have no pull
request of their own. Labels are cosmetic and never read back — the unit store
is the truth, so a stale label on a PR changes nothing; a label that cannot be
written is logged and the unit carries on. Azure DevOps keeps labels (it calls
them tags) but no colour or description, so a state is told apart by its name
there; everything above works the same.

A **draft** pull request means the pipeline is working on it: it is made a draft
while its unit runs and published when the unit is back in review, so a reviewer
reads a draft as "not yet" and a ready pull request as theirs to review.

## A change's lifecycle

1. The change is authored in `openspec/changes/<change>/` and committed
   (`abk check` and `abk tags` first).
2. The next tick's planner reads its `tasks.md` and adds units to the graph.
3. Units build in dependency order, at most `limits.max_concurrent_stacks`
   at a time. No unit that has never started starts while the units in
   progress across all repos are at `limits.max_units_in_progress`, and a pass
   starts no more new units than fit under it: the rest stay `planned`, and
   the tick log and `abk status` say "queue is full: N units in progress,
   limit M" with the count in each state. A place frees when a unit's PR is merged or closed, when a
   unit is held (a held unit does not count until it is requeued), or when a
   failed unit is requeued (`abk requeue`) and finishes, or is closed. Free slots go to
   open-PR work first (reworks, restacks), then resuming builds, then new
   units. Each builds only its own task groups, never a later unit's, even
   when the tasks for one are visible right there in `tasks.md`, and ends
   `in_review` with a PR — or `satisfied`, with no PR, if a predecessor
   already did the work.
4. Humans review and merge. A merge restacks whatever was on the branch.
5. When every unit is merged or satisfied, the tick deploys the change (`deploy.rules`),
   runs its tier 2 tests and — if it passes — archives it: the delta specs
   are folded into `openspec/specs/` and the change moves to
   `openspec/changes/archive/`.

If a verification fails, the change stays unarchived and `runs/verified.json`
holds the failure; `abk verify <change>` reruns it once the cause is fixed.

If an archive fails (a conflict between changes), the tick logs it and carries on, and
tries it again next tick; fix the conflict by editing the change. A finished change whose
directory is gone is logged as withdrawn and skipped.

## When the pipeline is paused

`abk status` prints `paused until … — <reason>`. The usual reason is the
usage windows: no new unit starts above the threshold for the window named
in the reason — `usage_pause_pct` (in the `session` or `weekly` section of
`runtimes.claude_code.limits`) for most of a window, rising to its
`usage_pause_ceiling_pct` as that window's reset nears, when one is set — and a resume is
scheduled for when the rising threshold would clear the current usage, or
for the reset. A pause never ends before it was written: a reset already past counts as unknown
(retry in thirty minutes), and a reading too old to trust pauses for
`usage_stale_retry_minutes` (five by default) and says it is stale. Times are local. Nothing needs doing; a tick before that time exits without
work. `abk status` prints each window as `used%/threshold%` with its time to
reset, which is what explains a pause at a percentage the configured floor
alone doesn't account for. A refusal by the guard pauses only the unit that asked: the
pass keeps running its rounds, asks the guard again at each, and resumes the unit once it
allows. Only a pause written because the model refused a build holds every start until its
deadline.
