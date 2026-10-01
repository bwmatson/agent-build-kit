---
name: abk-pipeline
description: TRIGGER — read when asked what the abk pipeline is doing, why a unit or change is stuck, what `held`/`failed`/`in_review` means, or before running `abk tick`, `abk verify` or `abk archive` in a planning repo. SKIP when the question is about writing a change's tasks (abk-authoring) or about abk.yaml and `abk doctor` (abk-config).
version: 1.0.0
generatedBy: agent-build-kit
---

# Reading and driving the abk pipeline

The pipeline runs unattended: a timer calls `abk tick` every few minutes in
the planning repo. A tick is one pass — check the usage window, poll GitHub,
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
| `abk status` | Whether the pipeline is paused, the usage reading, units by state, and which PRs are waiting for a human. Never changes anything. |
| `abk graph` | Regenerate the unit graph page (`docs/unit_graph.md`) from `runs/units.json`. |
| `abk tick --dry-run` | Run a tick's reasoning — poll, plan, work out what is ready — and report it without building anything. |
| `abk tick` | A real pass, the same one the timer runs. Safe at any time. `--only <unit>` builds just that unit if it is ready. |
| `abk verify <change>` | Deploy a fully merged change and run its live (tier 2) tests, then archive it. The tick does this on its own once every unit of a change has merged. |
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
| `planned` | In the graph, waiting for its dependencies and a free slot — or, with a `paused before <step>` note, a unit stopped there because the usage window filled and will resume at that step. A step already running is never interrupted; an empty step (an agent that finished having written nothing) against an exhausted window is one of these pauses, not a failure. | Nothing. `abk tick --dry-run` says whether it is ready. |
| `running` | A worktree is open and an agent is in the build/review loop. | Nothing. A run interrupted mid-way is reclaimed by the next tick. |
| `in_review` | The loop and tier 1 passed; the PR is waiting for a human. | Review the PR. A comment sends it back for rework; a merge moves it on. A branch that stops merging into its base sends it back to `planned` by itself; `abk status` marks such an entry `cannot be merged`. |
| `merged` | Landed. | Nothing; the change archives once every unit is merged and verified. |
| `closed` | The PR was closed without merging. | Units stacked on it are left as they are; re-plan if the work is still wanted. |
| `held` | A reviewer took the unit over, the toolchain cannot build it, the review loop held it itself, a merge left it beyond `limits.stack_depth_rebase_cap` — a change only a human can make, an escalated class or disagreement, or rounds spent with a pushed branch and PR. The pipeline will not touch it (a depth hold is released by a later merge). | See below. |
| `failed` | The build raised. | See below. |
| `satisfied` | The unit's groups were already implemented — by an earlier unit that worked ahead of its own plan — so it added no commits of its own, and what was already at the tip passed tier 1. | Nothing; its groups are ticked and its dependents released, the same as a merge. No PR was opened — or, if a rework found this after one was already open, the reason (the groups, that they were implemented elsewhere, and where when the graph can say) was posted on it and it was closed. |

### `held`

Four ways in: a reviewer put the `agent-hold` label on the PR, the review loop
itself held it, a merge left it deeper than `limits.stack_depth_rebase_cap`
(the history note names the depth and the cap, and the branch it is still on),
or the tick found it cannot build the unit (the unit's `history` entry says
which — a toolchain profile the framework does not implement yet, for
instance).

- A reviewer's hold: the human is driving. Finish the PR by hand, or remove
  the label and comment what should change; the next poll picks either up.
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
  id as `fixed`, `open` or `declined`. The unit's `review_rounds` keep each
  round's findings, ids and the commit it judged; a required finding, or an
  earlier one left open or unanswered, means the round is not an approval.
- A toolchain hold: nothing a retry fixes. Either build the unit by hand on
  its branch, or change the plan.
- A depth hold: no action needed. Its PR was retargeted, and a later merge in
  the same repo restacks it once its depth is within the cap. To move it
  sooner, raise `limits.stack_depth_rebase_cap` or restack the branch by hand.

### `failed`

The run raised an exception; its last log line in the tick output says
which. Fix the cause first — a missing credential, a broken toolchain, a
branch someone deleted — then set the unit's `state` back to `planned` in
`runs/units.json` and let the next tick take it. Do not mark it `planned`
without a fix: it will fail the same way and cost a run.

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
written is logged and the unit carries on. Azure DevOps keeps no labels: no
state label or change label appears there, and `agent-rework` is left on and
acted on once.

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

## When the pipeline is paused

`abk status` prints `paused until … — <reason>`. The usual reason is the
usage windows: no new unit starts above the threshold for the window named
in the reason — `limits.usage_pause_pct` for most of a window, rising to
`limits.usage_ceiling_pct` as that window's reset nears — and a resume is
scheduled for when the rising threshold would clear the current usage, or
for the reset. Nothing needs doing; a tick before that time exits without
work. `abk status` prints each window as `used%/threshold%` with its time to
reset, which is what explains a pause at a percentage the configured floor
alone doesn't account for.
