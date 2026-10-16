---
name: abk-pipeline
description: TRIGGER — read when asked what the abk pipeline is doing, why a unit or change is stuck, what `held`/`failed`/`in_review` means, or before running `abk tick`, `abk verify` or `abk archive` in a planning repo. SKIP when the question is about writing a change's tasks (abk-authoring) or about abk.yaml and `abk doctor` (abk-config).
version: 1.1.0
generatedBy: agent-build-kit
---

# Reading and driving the abk pipeline

The pipeline runs unattended: a timer calls `abk tick` every few minutes in
the planning repo. Once a tick has work, and before its round, it keeps the
pipeline's environment current: it runs `environment.sync` when the listed
inputs changed, then `environment.check`, and syncs once more if the check
fails. If the check still fails the tick starts nothing and exits 1 with the
check's output, with no unit failed; fix the environment (`abk doctor` runs the
check) and the next tick resumes the units waiting for it. `abk policy check` says whether the agent's own configuration refuses what abk forbids; it reads the configuration and starts no agent. A tick is one pass —
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
| `abk status` | Whether the pipeline is paused, the usage reading, the environment's state (healthy, or unhealthy with the check's output), units by state, which PRs are waiting for a human, any `held` or in-flight `planned` unit with `no recorded cause`, and the ready queue in start order with the reason for each place (priority, `stack age, from <unit>` when the oldest unit waiting on it was planned earlier, or planned order), and any failed unit that others wait on, with how many and a requeue hint. A `deadlocked: A -> B -> A` line, once per cycle, means planned units wait on each other and none can start (the pass says `nothing can start: deadlocked: …`); replan or edit the `Needs:` line, nothing breaks it for you. Never changes anything. |
| `abk graph` | Regenerate the unit graph page (`docs/unit_graph.md`) from `runs/units.json`. |
| `abk tick --dry-run` | Run a tick's reasoning — poll, plan, work out what is ready — and report it without building anything; it does not sync the environment or resume units waiting for it. |
| `abk report --waits [--by unit\|day] [--json]` | Each unit's wall time by cause (blocked, ready, agent, checks, other, in review for a person, review rounds, paused, failed), the hours the pipeline ran nothing split into a full queue and room to spare, and the estimate ratio per kind. A cause never recorded prints as `-`. |
| `abk tick` | A real pass, the same one the timer runs. Safe at any time. `--only <unit>` builds just that unit if it is ready. |
| `abk verify <change>` | Deploy a fully merged change and run its live (tier 2) tests, then archive it; exits 1 if it fails or passes without the change being archived. The tick does this on its own once every unit of a change has merged. |
| `abk check` | `openspec validate --all --strict --json` on the planning repo. |
| `abk tags <change>` / `abk tags --all` | Validate a change's task-group tags (see abk-authoring). |
| `abk planning split --repo <key> --to <dir>` | Move a repo's changes, specs and unit records to another planning repo. Always run the dry run first (the default) and read the plan; then `--apply`, then `--apply --remove` to take what moved out of the source. Units must be settled; see `docs/cli.md`. |
| `abk archive <change>` | `openspec archive <change> --yes`. |
| `abk openspec -- <args>` | Any other OpenSpec command, in the planning repo. |

## When the planning repo is also a code repo

A repo can be both: `abk.yaml` lists it at `.`, and the specs, the state and the
code live in one repository. Your **working copy** is where you work; the
pipeline never changes its branch, files or index. The **pipeline worktree** is
a detached worktree outside the repository, made by `abk install-timers`, where
ticks and tracks run. `abk status` and `abk doctor` in the working copy name it
and print `abk --config <worktree>/abk.yaml <command>`; `abk tick`, `abk track`,
`abk verify` and `abk archive` refuse from the working copy unless that
`--config` (or `ABK_CONFIG`) is given. Commits there are limited to the planning
paths (the specs directory, the state directory, the two generated pages and
`abk.yaml`).

Before a tick or track the pipeline worktree is synced to the tip of the default
branch. A line `planning sync stopped: <reason>` means the sync could not move it
and the run ended with exit 1; nothing was stashed or reset. The reason says what
is in the way: `diverged` (commits made in the pipeline worktree that the default
branch lacks), an unfinished merge, rebase, cherry-pick or revert, or a stray
branch. To fix it, go into the pipeline worktree, finish or abandon what is
unfinished, or move its own commits onto the default branch (or drop them), leave
HEAD detached, and let the next tick sync again.

## Where the state is

- `usage-ledger.jsonl` (the state directory) — one row per agent call. Besides the unit
  graph's nodes it holds `restack`, the conflict resolver's call with the unit being moved,
  and the calls made outside any unit: `plan`, `track_<phase>`, `init_research`,
  `init_propose`, `login_refresh`, `chat`, `chat_commit`. A row with a blank
  `unit` belongs to no unit: it is spend, shown as pipeline overhead, and never counted as a unit.
- `runs/units.json` — every unit the planner has produced, with its state,
  branch, PR number, review rounds and history. The file is the truth; the
  graph page is a view of it. Read it; only edit it as described under
  `failed` below. A unit's `run_log` names its latest run's file under
  `runs/unit-logs/` (the state directory): that unit's lines, with the step
  and model in its header and the outcome at the end.
- `docs/unit_graph.md` — the unit graph, regenerated on every state change:
  which unit waits on which, and where each one is.
- `runs/paused.json` — a record of the last pause, shown by `abk status`; says until when and
  why. Only a `rate_limit` pause (the model's refusal) holds starts; a usage pause refuses
  nothing, since the guard is asked again every round.
- `runs/decisions.jsonl` — why each unit that is not running is waiting (blocked, queue_full,
  slot, usage_pause, lease, backoff, waiting_review, needs_person, ready), one line each time
  the reason or what it waits on changes, and a `none` line when the wait ends.
- `runs/verified.json` — the outcome of each change's verification.
- `openspec/changes/<change>/` — the change a unit belongs to; its `tasks.md`
  is ticked as units pass review.

## Unit states

A **unit** is one PR's worth of work in exactly one repo, built from one or
more task groups of a change.

| State | Meaning | What to do |
|---|---|---|
| `planned` | In the graph, waiting for its dependencies (a never-started unit with two open same-repo parents, neither built on the other, builds on the deeper and waits for the rest: `waiting for <parent> to merge (second open parent)` in `abk status`) and a free slot — or a unit held before a step, which its next run decides again from the branch. A pass lets such a unit back in only when it was sent back for rework or its base changed, or when it was parked with the cause `host_unavailable`, `network_unavailable` or `service_unavailable` (the code host, the network or the model service could not be reached) and its backoff of 1, 2, 5, 10 then 30 minutes by consecutive parking has elapsed — it then resumes at the failing step, and an approved, pushed unit goes straight to the pull request step; any other cause waits for the next pass, and the tick log names it. A step already running is never interrupted; a usage pause leaves the unit `running` (below), not `planned`. | Nothing. `abk tick --dry-run` says whether it is ready. |
| `running` | A worktree is open and an agent is in the build/review loop, or the run was killed or paused for the usage window and its thread is interrupted. | Nothing. A killed run is resumed at the node it was in by the next tick; a usage pause resumes on the first tick the usage guard allows. Status, the graph and the label may name it `reworking` (answering review or check feedback) or `rebasing` (a conflict or moved base), or `paused` (a pause is in force and no run holds it; it resumes by itself): derived names, never stored, for a stored `running`. A PR is a draft while its unit is `running` or `planned`. |
| `in_review` | The loop and tier 1 passed; the PR is waiting for a human. | Review the PR. A comment sends it back for rework, and a comment added while that rework runs is addressed by it before it pushes; a merge moves it on. A branch that stops merging into its base sends it back to `planned` by itself; `abk status` says `conflicts with <base> since <time>; moved N times` and what it waits for; a conflict that survives its attempts, or one an attempt changed nothing for, holds the unit with that reason. It also leaves review for `planned` (read as `paused_rework`) while a predecessor in the same repo is changing its branch, and returns by itself once that predecessor is back in review; the move is an `upstream_changed` event to its thread. |
| `checking` | Shown, never stored: a unit in review whose checks are still running, or that was pushed moments ago with none yet. It counts as in review for scheduling and dependents. `abk status` lists it as `checking`, apart from `awaiting review`. | Wait; it reads `in_review` once its checks pass, or a repo with no checks has waited `global_limits.checks_register_seconds`. |
| `merged` | Landed. | Nothing; the change archives once every unit is merged and verified. |
| `closed` | The PR was closed without merging. | Units stacked on it are left as they are; re-plan if the work is still wanted. |
| `held` | A reviewer took the unit over, the toolchain cannot build it, the review loop held it itself, a merge left it beyond `global_limits.stack_depth_rebase_cap` — a change only a human can make, an escalated class or disagreement, or rounds spent with a pushed branch and PR. The pipeline will not touch it (a depth hold is released by a later merge). | See below. |
| `failed` | The build raised. With the cause `environment`, the pipeline's own environment failed its `environment.check` before tier 1; the unit keeps its slot, `abk status` says it is waiting for the environment, and the tick resumes it once the environment is healthy. | See below; for the environment cause, fix the environment (`abk doctor` runs the check). |
| `satisfied` | The unit's groups were already implemented — by an earlier unit that worked ahead of its own plan — so it added no commits of its own, and what was already at the tip passed tier 1. | Nothing; its groups are ticked and its dependents released, the same as a merge: a pull request stacked on it is moved onto its predecessor's branch or the trunk and retargeted before the satisfied unit's own is closed. No PR was opened — or, if a rework found this after one was already open, the reason (the groups, that they were implemented elsewhere, and where when the graph can say) was posted on it and it was closed. |

### `held`

Four ways in: a reviewer put the `agent-hold` label on the PR, the review loop
itself held it, a merge left it deeper than `global_limits.stack_depth_rebase_cap`
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
  sooner, raise `global_limits.stack_depth_rebase_cap` or restack the branch by hand.

### Waiting for a tier 2 split

A unit whose tier 2 tests sit in a held split waits with the reason "waiting for tier 2
split <name>" (cause `split_held`) until `abk tier2 release <split>`, or until the configuration
sets `hold: false` for the split (removing a `hold: true` line frees it only when
`tier2-held.json` has no entry for it). `abk tier2 status` shows each split as usable or held, and
`abk tier2 check` lists the splits with their test counts and finds a test in two.

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
to `global_limits.max_check_rounds` times (3 by default, counted per review round; `null` for no limit) before it fails with the output kept.

Fix the cause first where it is outside the branch — a missing credential, a
broken toolchain, a branch someone deleted — then `abk requeue <unit>` resumes
it where it stopped. Where the failure is in the branch's own work (a type
error, a failing test) a plain requeue meets the same failure again; use
`abk requeue <unit> --rework` to keep the work and hand the agent the saved
output. `--restart` throws the attempt away. To tell the agent something a task
is too small for, add `--note TEXT` (or `--note-file PATH`) to `--rework` or
`--restart`: the agent sees it first, ahead of any saved failure, as a person's
instruction that wins where they conflict, and the review that follows is told
it. With a note, `--rework` needs no saved failure; a plain requeue refuses a note. Never edit `runs/units.json` by
hand: a failed unit remembers its step, and putting it back to `planned` alone
sends the next run past the agent to a check on the same branch.

A plan is made when a change's `tasks.md` changes, not on every tick. Run
`abk replan <change>` (or a unit id, `--all`, `--failed`) to plan again now when a
unit waits on a dependency it no longer needs (a `Needs:` line changed in another
change), when a change gave up planning (the tick logs it, and `abk replan` with no selector lists each change's plan state), or when
neighbouring changes' units changed since it was planned. Started work is never
touched; `--forget` only clears the record and leaves the planning to the next tick.
A plan state of `waiting for the network` or `waiting for the model service` is an outage,
not a failure: no attempt is used and the tick plans it again after its next try (or when
the network pause clears); nothing needs running. `given up` names `abk replan --failed`.

A unit with a `Needs:` line whose dependency is not yet in review waits instead:
`abk requeue` leaves it `planned` with the cause `gated` (shown by `abk status` as
waiting), and the tick resumes it in the requeued mode, restacked onto the dependency's
branch, once it is in review. The graph draws a `Needs:` dependency as a thick edge
labelled `needs`.

A test that failed under load and passed twice alone is a flake, not a failure: the unit is
parked the same way (`gated`, its note names the test) with a `Needs:` line on the one
change the pipeline wrote to fix that test. `abk status` lists each flaky test as `flaky:`
with its count and fix change; the unit resumes at tier 1 once that change merges. The one
exception is the scoped run after a clean move of the base: a flake there is recorded and
its fix change written, but the unit is not parked and gains no `Needs:` line. More than
`global_limits.max_flakes_per_run` (default 5) such tests in one run is a disturbed run, not that many
flakes: tier 1 records one `storm` row (`abk status` shows it as `flake storm:`), writes no change,
and goes on with the checks that remain.

At each planning pass a planned unit that never started, whose change no longer exists, becomes
`unplanned`, and a unit waiting on it stops waiting; a started unit is left as it is.

A test that fails tier 2 on the base as well is pre-existing: it is recorded in
`preexisting-failures.jsonl` and gets one `fix-failing-<test>` change, written without a
model (a successor only once the earlier one is merged and archived). `abk status` lists
each as `pre-existing:` with its count and fix change. The fix changes of both kinds are
written at `Priority: 1`. `abk tick --dry-run` prints `exists: <change>` or
`would write: <change>` for each recorded one and writes nothing. A unit whose tier 2
failures are all pre-existing is parked `gated` on those fix changes (a `Needs:` line on each
group) and runs tier 2 again, restacked, once they merge; a unit with a failure of its own
fails as before and is shown only its own failures. A unit about to run a full tier 2 run is
parked the same way, before the lock and any test, while a recorded fix change in its repo is
open (the fix's own units and units already waiting on it run); it resumes once the fix is
in review. `abk status` ends each `pre-existing:` line with how many units wait on its fix.

Under `e2e_unit_scope: own` (the default; per repo `tests.e2e_unit_scope`) a unit's tier 2 run covers only the tier 2 tests
its branch added or changed, selected by identifier and the marker; with none it runs and locks
nothing and says `tier 2 skipped: no tier 2 test added or changed`. It runs the whole marker
where it cannot narrow, or under `full`; a scheduled unit is always `full`.

`e2e_schedule` (`daily`, `weekly`, `monthly`, `off`; per repo `tests.e2e_schedule`) makes a
round write `scheduled-tier2-<repo>-<date>-<split>` before planning, ahead of the usage guard,
when a split of a repo is due; the date is read from the names of its open and archived
scheduled changes, and one is open per split. Its unit goes from `prepare` to the whole-suite tier 2 step with no agent
call or pull request, ends satisfied on a pass, and a failure goes through the pre-existing/fix
flow above. A due repo keeps a tick from being idle. `abk tick --dry-run` prints
`would write: <change>` or `exists: <change>`. The `scheduled-tier2-` prefix is reserved.

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

## Holds and their exits

`abk approve` only records a person's approval for a review round; it changes no
state, so approving a held unit does not release it. A unit leaves `held` by one
of the exits below, and which one depends on how it was held.

| Hold (`held_by`) | Who acts | Exit | What happens next |
|---|---|---|---|
| The `agent-hold` label (`reviewer`) | A person | Remove the label (release) | The next poll returns the unit to `in_review`. |
| The review loop (`review`) | A person | Decide the point, then `abk requeue` (`--rework` or `--note` where useful); or finish the pull request by hand (merge) or close it | Requeue runs the unit again from its branch; a merge or close is recorded by the next poll. |
| A merge left it beyond the depth cap (`depth`) | Nobody | A later merge in the same repo restacks it; to move it sooner a person raises `global_limits.stack_depth_rebase_cap` or restacks the branch by hand | The unit leaves `held` when restacked. |
| The toolchain cannot build it (`toolchain`) | A person | Build the unit by hand on its branch, or change the plan; `abk requeue` alone fixes nothing | The same failure returns until the cause is changed. |
| Parked, `dirty_worktree` | A person | Commit or remove the changes in the worktree, then `abk requeue` | A requeue while the tree is still dirty leaves it parked. |
| Parked, `attached` | A person | Start `abk serve` again, or `abk attach release <unit> --commit "MESSAGE"` or `--discard`, then `abk requeue` | The unit stays held until requeued. |

Release applies only to a hold the `agent-hold` label made; for a review-loop
hold the exits are requeue, merge or close. The sections under `held` above give
the detail of each.

## Why a unit is held "needs a human"

Almost always this is a limit of the builder, not a decision. What the builder
cannot do, and what a person does about it:

- It cannot edit planning-repo files (`follow-ups.md`, a change's `spec.md` or
  `tasks.md`): make the edit in the planning repo, then requeue the unit.
- It cannot run a live or credentialed check: run the check yourself and record
  the result, or reword the task so it needs none.
- It cannot write a sensitive file the agent harness refuses to let it edit (a
  hook configuration, for instance): make that edit by hand on the branch.
- It cannot run `uv lock` where the agent's tool list lacks it: run it by hand
  and push the lock file.

## When nothing is moving

- User timers only fire while the systemd user manager runs, and without
  lingering that is only during a login session. Check `loginctl show-user
  "$USER" --property=Linger`, run `loginctl enable-linger "$USER"` if it says
  `no`, and reinstall with `abk install-timers`. `abk doctor` warns when
  lingering is off.
- A unit marked `running` with no process was cut off, by the user manager
  stopping or by a tick killed from outside. Run a tick by hand, never under a
  timeout: killing the pass leaves this picture. The
  next tick that finds no process resumes the unit.
- A full queue starves ready work: running, in review and failed units (and
  planned ones already worked on) count against `limits.max_units_in_progress`;
  held, blocked and merged, closed or satisfied units, and failed units waiting
  on another, do not. A failed unit holds its slot until it is requeued and
  finishes, or closed: free one that way.
- Usage is read with `abk report --by role|model|change` (cost) and
  `abk report --context` (context window use). The ledger does not record
  what a runtime does not report.

## A change's lifecycle

1. The change is authored in `openspec/changes/<change>/` and committed
   (`abk check` and `abk tags` first).
2. The next tick's planner reads its `tasks.md` and adds units to the graph.
3. Units build in dependency order, at most `project_limits.max_concurrent_stacks`
   at a time. No unit that has never started starts while the units in
   progress across all repos are at `project_limits.max_units_in_progress`, and a pass
   starts no more new units than fit under it: the rest stay `planned`, and
   the tick log and `abk status` say "queue is full: N units in progress,
   limit M" with the count in each state, then "N blocked not counted" and a
   `blocked: <unit> … waits on <unit>` line for each, and "N failed waiting not
   counted" for failed units that wait on another unit (they stay failed, and
   count again when the wait ends). A planned unit that waits on
   another unit is blocked and holds no place however much work it has; the unit it
   waits on starts into that place first, and when the waiter is no longer blocked it
   starts only while there is room. A place frees when a unit's PR is merged or closed, when a
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

## Restacks

A unit whose base moved is moved by the restack lane, beside the build workers and outside
`max_concurrent_stacks`. `abk status` prints `restacks: N running, M waiting` with each unit as
`restacking onto <base>`; a restack whose conflict needs the agent while a usage pause stands is
listed as `restack waiting: <unit> — usage pause until <time>` and is moved when the pause ends.
A clean move needs no agent and proceeds during a pause.

## When the pipeline is paused

`abk status` prints `paused until … — <reason>`. The usual reason is the
usage windows: no new unit starts above the threshold for the window named
in the reason — `usage_pause_pct` (in the `session` or `weekly` section of
`runtimes.claude_code.limits`) for most of a window, rising to its
`usage_pause_ceiling_pct` as that window's reset nears, when one is set — and a resume is
scheduled for when the rising threshold would clear the current usage, or
for the reset. A pause never ends before it was written: a reset already past counts as unknown
(retry in thirty minutes), and a reading too old to trust pauses for
`usage_stale_retry_minutes` (five by default) and says it is stale. Times are local. Nothing needs doing; the next tick asks the guard again and starts work
when it allows, whatever time the pause named. `abk status` prints each window as `used%/threshold%` with its time to
reset, which is what explains a pause at a percentage the configured floor
alone doesn't account for. A refusal by the guard pauses only the unit that asked: the
pass keeps running its rounds, asks the guard again at each, and resumes the unit once it
allows. Only a pause written because the model refused a build holds every start until its
deadline.

A `network` pause is written when a unit parks for the network (never for the model
service) and `abk status` shows it as `waiting for the network — <reason>`. It ignores its
deadline: only a tick whose control hosts connect ends it, and until then no unit starts and
nothing is planned. Nothing needs doing.
