# Architecture

How a change becomes merged, deployed and archived code, and what stops the
unattended parts from doing harm. The examples use a workspace of two repos,
`app` and `platform`, where `app` consumes `platform`.

## The flow

```
change (tasks.md) ─► plan ─► units ─► build ─► PR ─► review ─► merge
                                                         ▲          │
                                     poll: rework/restack┘          ▼
                                                     verify ─► archive
```

The build agent never merges. The pipeline merges a unit review classified `auto` and policy
allowed; a person merges what was not auto-landed.

Everything below is a tick (`abk tick`), which a timer runs every few minutes
in the planning repo. One tick starts with a round, in order: check the usage
window, fetch and poll each repo's host, plan what is new, reclaim what no run
holds, verify and archive what has fully merged, retry the closes and replies owed,
take stale state labels off finished pull requests, and work out what is ready;
then it builds that. Every step is idempotent, and a tick with
nothing to do exits silently before reading usage or calling any host.

Once a tick has found work, and before its first round, it keeps the pipeline's
environment current (`pipeline/environment.py`). When `environment` is configured it
hashes the listed inputs and compares them with the hash recorded in the state directory,
runs `sync` when they differ, then runs `check`; a failing `check` runs `sync` once more
and checks again. If it still fails, the tick records the environment as unhealthy with
the output, starts nothing and exits non-zero. `abk status` prints the recorded state.
Units failed with the cause `environment` are resumed in the pass once it is healthy.

A repository's own `environment` runs in the unit's worktree (`prepare_worktree`): in the
tests node and before every unit-test it hashes the inputs there, runs `sync` when the hash
differs from the one recorded in the worktree's git directory, then `check`. A failure with
inputs equal to the base branch's (at the point the branch left it) fails the unit with the
cause `environment`; a failing `sync` or `check` after the unit changed the inputs is an
ordinary unit-test failure carrying that output.

The lock files named in the repository's `environment.inputs.lock` belong to the pipeline in
its worktrees, because a package manager's `sync` creates or rewrites them. The commit step
(`build_commit`) commits a tracked lock with the unit's change when the unit changed a
dependency input against its current base (the point its branch left it), and otherwise
restores it to the branch's version; a lock the branch does not track is never committed and
stays in the worktree. A restack restores an unchanged tracked lock before it moves the
branch, since a rebase refuses a tree with an unstaged change. The same rules apply to a
commit adopted from a chat.

The files a toolchain profile says its own commands create (`created_files`) are owned the
same way in a repository with no `environment` section, so a unit-test command that writes one
does not hold the next step as a dirty worktree. `owned_paths` merges them with the lock files
and artifacts, one entry per path, an artifact before a lock before a created file. An
untracked one is never committed; a tracked one follows the lock rule only where the
environment declares dependency inputs to compare, and is ordinary work otherwise.

Inputs are path patterns (`path_patterns.py`), and one matcher serves the hash, the
comparison against the base, lock ownership and artifact ownership. The hash covers each
pattern as written, the sorted files it matches and their contents, and a pattern matching
nothing counts as missing. `environment.artifacts` names what `sync` and `check` produce,
such as a dependency folder: matching skips anything under an artifact, so filling one never
changes the hash, and in a worktree an untracked artifact is neither a leftover that holds a
unit nor staged by the commit step. A tracked file under an artifact pattern is ordinary
work.

### 1. An OpenSpec change

A change lives in `openspec/changes/<change>/` in the planning repo:
`proposal.md`, `design.md`, delta specs, and `tasks.md`. The pipeline reads
only `tasks.md`, so two facts have to be on every task-group heading — the
repo the code lands in, and the test kind it needs:

```
## 1. [platform] [unit-test] [contract] Accept the new field, keep the old one
## 2. [app] [unit-test] Send the new field
## 3. [app] [e2e-test] [acceptance] Drive the route end to end as a client
## 4. [platform] [unit-test] [narrow] Drop the old field
```

`abk tags` (`pipeline/work_graph.py`) checks the contract; the planner
refuses a change with tag errors before spending a model call on it:

- groups are numbered from 1 in build order, every group has at least one
  `- [ ] n.m` task, and `[repo]` is one of `abk.yaml`'s `repos` keys exactly;
- the kind tag is one of three, listed from narrowest to widest. `unit-test` covers one
  module's behaviour and runs in CI with no external services. `integration-test` covers
  behaviour across modules or files in the ordinary suite with no live stack, and behaves as
  `unit-test` in every other way: it is a label, not the pytest `integration` marker and not
  `tests/integration/`. `e2e-test` needs the real stack on the developer host and is
  serialized behind one lock. A unit of several groups takes the widest kind among them;
- an optional third tag is a **flag**. `[contract]` marks a group that widens
  a shape the *other* repo consumes (a wire model field, an event, a tool
  surface). Two repos are never at the same commit, so callers of both shapes
  exist for a window; the widening lands alone and a `[narrow]` group — which
  must be last — removes the old half. Contracts inside one repo need no flag.
  `[acceptance]` marks the group that drives what the change built the way its
  consumer does, on the stack; it is always `e2e-test`, comes after every group it
  exercises (only `[narrow]` may follow), and gets a unit of its own. Every
  change has one or opts out with a line `Acceptance: none — <reason>`; the
  reason is what review agrees to, and the line without one is an error;
- a `Needs: <other-change> group <n> — why` line inside a group makes it wait
  for a group of another change. The planner orders groups within a change;
  across changes it only sees what is in flight, so a dependency that must
  hold is written down and applied as code (`link_needs`, every tick).
  `Needs: <other-change> group <n> — why` makes the dependent start on the
  parent's branch once the parent is in review: a review edge. An edge is a
  merge edge for three reasons only: it crosses repositories (a plain `Needs:`
  to a group of another repo is read as a merge dependency, with an info note,
  so cross-repo is always merge), the author wrote `merged` straight after the
  group number, or its dependent is a failed unit waiting on the parent. A merge edge
  holds the dependent until the parent has merged and a later tick has the
  merge in the code it runs: the tick records its number, start time and the
  kit checkout's head in `tick.json`, and the loaded code test is whether that
  head contains the parent's merge (for a parent in another repo, whether the
  tick is a later one than the tick that saw the merge). `link_needs` records
  the dependency as `needs` and, for a merge edge, also as `merge_needs`,
  recomputed from `tasks.md` every tick, so the graph can draw it thick and
  label it `needs, merge`. Write `merged` only when the dependent must run
  against code the pipeline itself runs, or against a parent's merge that
  nothing else in the checkout shows; a fix change a failed unit waits on needs no `merged`;

### 2. Planning into units

A **unit** is one PR's worth of task groups, in exactly one repo and one project of it
(`Unit.project`). It has one
identity, its first change's id and branch, and may also carry groups of other
changes (`Unit.joined`); `Unit.members()` is the single way to ask which
change's groups it builds, its own first. Building, review, ticking, archive
readiness, `Needs:` resolution, the pull request body and the graph all read
members. Once per
change — and again only when the change's specification changes (its
`tasks.md` with checkboxes and `Needs:` lines stripped, hashed into
`runs/planned.json`) — the planner (`pipeline/planner.py`) sends the change,
the units already in flight (the list omits merged and satisfied units of other changes, which are in the trunk and cannot affect a plan, and says how many it left out) and `abk.yaml`'s `relationships`/`consumes` prose
to a model and gets the whole graph back as JSON: a label for each unit (used only inside
that reply), repo, tier, `depends_on`, `estimated_lines`, `groups`. The change text it is sent marks the
heading of each group a started unit builds `(built by <unit id>)`, and the prompt says
such groups are taken and never claimed; a plan that claims one is still refused. A
refused plan keeps the labels the planner gave its units and the reason in the plan record, which a bare
`abk replan` shows. Once the plan is checked, the program names each unit
`<change>/<lowest group>` and rewrites `depends_on` from labels to ids. It will reuse the id of an
unstarted stored unit with exactly the same groups, whatever its number, so a replan renumbers
nothing; when the id is retired, started or finished, the unit takes the next free integer
above every number the change has used. Every failed attempt stores its `reason`: the first line of the error,
at most 300 characters, redacted. A planner prompt over the safe size of the runtime's
transport fails the attempt the same way, its first line naming the change, the size and the
limit and the lines after it the size of each part.

A replan that regroups sets the unstarted units it replaces `unplanned` and records, in each one's
`superseded_by`, the units that carry its groups. What a unit depends on is read through that field
(`current_dependencies`): a `depends_on` entry that names a replaced unit stands for its
successors, so the scheduler, the stack's base and depth, the restack, the cycle checks and the
diagram agree. `link_needs` then rewrites the stored `depends_on` to the successors, in any unit
that has not finished, started or not, and a join repoints `depends_on`, `needs`, `waited_on` and `superseded_by` onto the unit
that took the other in.

A planner call that ends on an outage (a network or provider failure, classified as a
unit's agent run is) is a wait, not an attempt: the record keeps its `attempts` and gains
`waiting` (`network` or `service`), `waits`, `since` and `until` (1, 2, 5, 10 then 30
minutes by consecutive waits). A wait is skipped, and not counted as work to plan, until
`until` passes; a network wait is due at once on the tick whose control probe clears the
`network` pause, which a network wait also writes and a tick under it plans nothing for.
Waits by HTTP status are counted apart (`service_waits`) and capped by
`global_limits.service_unavailable_attempts`; waits the probe found are not capped and not counted; an ordinary failure, a
success, an edit of `tasks.md` and `abk replan --forget` end a wait.

A model is used because the parts that matter are judgements — which groups
touch the same files, what depends on what across changes, how many small
groups make one PR (`global_limits.min_unit_lines`). Its output schedules real work,
so validation **refuses rather than repairs**: every group claimed exactly once
by a unit in its own repo, no group already built by a merged unit, no unknown
dependency, no cycle, the acceptance group alone in its unit and downstream of
everything it exercises. A bad plan costs one round; `global_limits.max_plan_attempts`
bounds the retries per version of the file.

The plan's dependencies are also checked against every unit not finished: a planner
dependency that would close a cycle with stored work is dropped and logged, and a
`Needs:` dependency is checked as it is linked and refused if it would close one.

A unit is sized by its expected tier: its ceiling is the `review.ceilings` figure
for the highest review tier expected of its groups (a group counts at its floor, and a repo's override applies),
a unit with no expected tier is held to `full`, and a join takes the higher tier of its two sides.

Unit size is bounded from both sides. Groups are combined until the estimate
reaches `global_limits.min_unit_lines`, and never past the unit's ceiling (its expected tier's
`review.ceilings` figure, with `review.ceilings.full` for a unit with none): the
planner's prompt states the ceiling, and a plan with a unit estimated over it
is rejected and re-asked.
The estimate is checked after being multiplied by a calibration ratio for the unit's kind
(repo, tier and the flag of its first flagged group): the median of what the last
`global_limits.calibration_window` merged units of that kind landed at over their estimates, each
sample clamped, moved toward 1 when there are few, 1 under `calibration_min` samples, and
never below 1 or above `calibration_max`. The planner's prompt lists the ratios above 1,
each with the largest raw estimate the ceiling allows for the kind and its newest merged
units (title, estimate, landed lines; `calibration_examples`, `calibration_kinds_listed`,
and at most 2000 characters). A combined unit rejected for size is told that figure and
its group count, a join is held to the same figure, and a unit records both its own
estimate and the calibrated figure when it is planned, which `abk status` lists; a sample
always uses the raw estimate, so the
correction does not compound. `global_limits.calibrate_estimates: false` turns it off.
A single group estimated over the ceiling cannot be fixed by grouping, so the
change is left unplanned with a message naming the group and saying its tasks
must be split, and no further attempts are spent on that version of the file.
The ceiling shapes plans only, and a unit never waits on it. An estimate counts
additions plus deletions over every file, generated files excluded. Opening a
pull request, and each push after it, records the unit's actual lines from the
host's per-file totals less the configured generated files; one over the ceiling
is logged and listed by `abk status`. A host that reports no per-file counts
(Azure DevOps today) records no actual size, so nothing there is flagged.
Failing to read the size never stops the unit.

**Joining.** The planner is also shown, for every unit of another change, whether
it is *unstarted* (`StoredUnit.unstarted`: planned, with no branch, commit, pull
request or step to resume at) and may return `joins` beside its units: a new
change's groups onto an unstarted unit, or one unstarted unit onto another.
The earlier unit stays, carrying the later's groups (`Unit.joined`); the later is
removed and what depended on it depends on the earlier. A join is accepted only
when `pipeline/joins.py` finds every rule held, else the round is refused: same
repo, project and tier; a straight line (the later depends on the earlier, nothing else
does, the later waits on nothing else unfinished); both unstarted; no
`[acceptance]`, `[contract]` or `[narrow]` group; no group marked `Separate:` or
`Independent:` (an `Independent: <reason>` group depends on no earlier unit of its
change, and is never joined into a neighbour's unit); the estimates together at
or under the joined unit's ceiling (the higher tier of its two sides). Joins are checked in order against a copy of
the store, so three units in a line can become one in a round. On the write each join is applied under both units' branch locks with
"unstarted" read again; a unit that has started since drops that join alone, the
rest of the plan is written, and the change is planned again next round. A group
another unit carries counts as built when its change is planned again. Each join
is logged with its groups, the unit and the combined estimate.

Joins are chosen by logical grouping first: work that belongs together, groups of
one change or of different changes that touch the same or closely related files,
is joined, and never two items merely because both are small. Only among candidates
that fit equally well is the more urgent work offered its partner first; a priority
never overrides a better fit. A joined unit takes the most urgent priority of its
groups. `check_joins` looks at no priority.

**Priority in the plan.** The planner is shown each group's priority and each
in-flight unit's, and is told to depend on a unit only for code it introduces. A plan
whose unit depends on an unstarted unit of a larger priority number is refused, as
`parse_plan` checks it, unless the unit gives a reason for the edge in
`needs_less_urgent` (dependency id to reason); a target that has started, merged,
closed or is satisfied is never checked. The refusal is recorded as any failed
attempt, and the next attempt's prompt carries it. A plan recorded before this is
not made stale by it: replan with `abk replan <change>` once to drop the edges that
were avoidable.

`UnitStore.upsert` merges the plan into `runs/units.json` by id: shape from
the plan, state/branch/PR/feedback from what is already recorded. A unit the
plan dropped becomes `unplanned` only if it never started; a planned unit with a branch, a
pull request, a pushed commit or an approval stays as it is and the replan prints `kept:`.

A group has one owner among the units that have not finished: a unit owns its groups while it
is `planned`, `running`, `in_review`, `failed` or `held`, or `unplanned` with work, and a
merged, closed, satisfied or retired unit owns none. `upsert` checks the store as the merge
would leave it and raises `GroupOwned`, writing nothing, when a plan gives a group to a unit
that did not carry it while a started owner does. `plan_all` then logs both units and the
way out (`abk retire` the owner, or edit `tasks.md`), records the plan as failed with its
attempts spent and the owners' ids, and does not ask the planner again until `tasks.md`
changes or `abk retire` forgets the record. A collision already in the store does not block a
replan; `abk status` lists it.

`abk replan` is the on-demand way to plan: it plans the changes it is given
whatever the recorded hash says, then links the `Needs:` lines, and prints what
changed. Linking only adds dependencies, so removing a stale one is the replan's
work: the plan rebuilds each planned unit's dependencies. `runs/planned.json` is
read, changed and written under a lock, and replaced atomically, so a command beside
a running pass loses no update.

### 3. Building a unit

A priority-0 unit starts as soon as it is ready, in its own emergency lane with its own cap
(`project_limits.emergency_extra`, 1 by default, 0 turns the lane off): the places and workers
of the project may be full. It counts toward the occupancy, so ordinary starts wait until the
occupancy falls below the limits, and it never delays a unit that is finishing: a rework, a
resume, a review round and a push keep the workers they had.

Each unit has a priority, 0 (emergency) to 5, 3 by default, set by the planner
in code from the `Priority:` lines of the groups it builds: the most urgent of
them, carried groups included. A started unit keeps the priority it started
with, and the store leaves the default out of a unit's record. `waiting_on_me`
(`pipeline/units.py`) answers which units wait on a unit, across repos and
through chains, and `effective_priority` takes the most urgent of a unit and
those waiting on it. An unstarted unit that a more urgent unit waits on is also
promoted: `promote_ancestors` stores the waiter's priority on it and the waiter's id in
`promoted_from`, at the end of planning and after `Needs:` lines are linked. The
promotion is recomputed on each pass, so it lapses once the waiter merges, closes or
loses the edge; a unit that started while promoted keeps it.

`ready_units` picks planned units whose dependencies allow: a same-repo
dependency may be `in_review` (the unit stacks on its branch), a cross-repo one
must be `merged` (stacks cannot span repos). A unit that has never started and has two
or more unrelated open same-repo parents (neither built on the other) waits for all but
one of them: it builds on the deepest and waits for the rest (see "Open parents" in
`docs/unit-graph.md`). A `satisfied` dependency is
looked through to what it was built on: same-repo, the dependent waits on and
stacks on that predecessor; cross-repo, it counts once that predecessor has
merged. `global_limits.stack_depth_build_cap` holds
back chains of open PRs; `project_limits.max_concurrent_stacks` bounds units being
built. `project_limits.max_units_in_progress` bounds the units started and not finished
in each project (or, once an installation names a Claude account, in each account, against that
account's own `max_units_in_progress`; the default account's units then count together across all its
projects against `project_limits.max_units_in_progress`): running, in review or failed, and any planned or unplanned unit
that a run has started: one with a recorded branch, a pushed or approved commit or a pull request. Merged, closed and satisfied
units, held units (set aside until a person releases them), and units that
never started, do not count. A planned or unplanned unit parked on a held split
(`parked_splits` set) holds no place whatever its cause field says; a parked unplanned unit
is left alone on release, and a replan keeps the park. A blocked planned unit does not count either, however
much work it has: it waits on another unit (`waiting_on`: a dependency or predecessor
not yet reviewed or merged, being reworked, failed or held, which covers a gate not yet
merged and an upstream that went back), and counts again when it no longer does. A
backoff, a lease, a limited tick and a usage pause do not make a unit blocked. Only a
unit that has never started is stopped by the limit, and no more of them start than
leave room, except a priority-0 unit in the project's emergency lane (above); so is a planned unit that was blocked and no longer is (its record carries
the cause of the wait, or a unit it depends on was outside review and merge since it last
changed state), which stays planned until the other units in progress are below the limit.
A failed unit that waits on another unit (`waiting_on`) does not count while it waits
either; it stays failed and counts again when the wait
ends. A failed unit is requeued by a person or when its wait ends: the pipeline requeues it once
when its wait ends (see `global_limits.wait_end_requeue`), never on a timer. A rework, resume, restack, review round, push and a unit paused by a usage pause or interrupted still run, so the count can
pass it. A blocked unit that had work gives its place to a ready, never-run prerequisite
it waits on (a handoff unit): one prerequisite starts for each blocked unit's
place (one unit for each place; several by effective priority, then effective age; it
starts among the new units by the order below, so it never goes ahead of a more urgent one),
within the limit and `max_concurrent_stacks`. A unit whose only reason to run is that its base moved runs
its whole moved-base run in the restack lane: the merge, release and depth handlers, and the poller on a conflicting
pull request, hand each such unit to the restack lane of the unit's project (each project has its own lane, with
`project_limits.max_concurrent_restacks` workers and a queue in the order restacks were seen, so a busy project does not
hold back another's) instead of restacking inline. The lane's cap bounds the moved-base run: it is the move, the
resolver, the port of a conflict the resolver could not settle and the checks and review of the moved branch, and it
stops before any work that is not about the move (a rework of other feedback, a fix of checks, the end-to-end tests, tests or implementation), leaving the unit
`planned` with a note naming the step for a build worker. A run is never held back by the limit on build workers, but
the run counts toward slot occupancy: no build starts while the occupancy is at or above `max_concurrent_stacks`, and the
occupancy may read over it. Each run counts as one attempt at the tip of the unit's base, bounded by
`global_limits.max_review_rounds`; a unit that spends them is held with `needs_human` and a note naming the base, the tip
and how the last run ended. A run the lane cannot go on with is handed back to a build worker, `planned` with the cause
`restack_handed_back`. Every agent call in a run asks the usage guard first. The limits are counted for each project,
not across all repos. Free slots then go to
units with an open pull request, then to those resuming a build, then to new
ones. The first two go in planned order; new ones go by effective priority, then handoff
units before the others of equal priority, then by effective age (the earliest planned position among the unit and every unit waiting on it, in
any repo), then by planned position. Ready units build in parallel threads, each
under a branch lock (`runs/locks/`) that fails fast: two runs on one branch is
a scheduling bug, not a queue.

A pass keeps scheduling until it runs out of ready work. Each build that
finishes — and, while builds are running, every five minutes regardless — is
followed by a fresh fetch and poll and a fresh `ready_units`, so a parent
reaching review starts its child, a dependency merging releases its dependent,
and a conflict or a review comment on an open pull request is heard, in the
same pass rather than the next. The timer cannot start a tick while one is
running, so a pass with one long build must not wait for it to look. A unit
the pass has already built and a poll then sends back for rework is started
again in the same pass, at most twice; anything else the pass started stays
handed out, which is what lets a pass end. The caps apply to every
evaluation, and `--only` narrows every one. The tick and each of those
refreshes run the same round (`run_round`): the usage check, fetch and poll,
planning, reclaim, the notification reconciliation, verification and archive, the
closes and replies owed, the state-label sweep, then readiness. A change added or
edited during a pass is planned by its next refresh (a change whose tasks are
unchanged costs no model call), a unit sent back is let in again, and a step
that raises is logged while the others still run. Only the model's own
refusal (a `rate_limit` pause, or a build returning False) ends submission,
and the builds in flight are still awaited. A usage refusal pauses only that
unit: a refused round still fetches, polls and archives, starts nothing, and
later rounds ask the guard again and resume it. A pass therefore
lasts as long as the work it can reach — watch the pass, not a unit.

**Notifications.** When `notifications.provider` is not `off`, every round ends its bookkeeping with a
reconciliation (`notify.reconcile`): the units are turned into the cards that call for a person,
the new ones are shown after `delay_minutes` and again after `remind_after_minutes`, and a card
whose reason has ended is cleared. A unit calls for a person when it is in review with no rework
pending, has failed, or is held for one. "No rework pending" is `feedback == ""` on an
`IN_REVIEW` unit (a gated send-back is `PLANNED` with `Cause.GATED`, so it needs no check);
"needs a person" is `HeldBy.REVIEW` or `HeldBy.TOOLCHAIN`, or `Cause.NEEDS_HUMAN`. There is no
person-activity signal yet: `pr_replies.own_posts` is not used, so a card does not clear because
the person has begun to answer. A provider that fails is logged and never fails the round.

A round reclaims too: a unit marked `running` that no process holds and that
has no thread to resume goes back to `planned`, so its state is true for as
long as a pause lasts. A unit in flight is left even before its
worker takes the branch lock, and a unit the pass already started is left until
the pass ends. A running unit
that no process holds takes no build slot until the round starts it again, and
is started before planned units. A change that
fully merges early in a long pass is verified live and archived by the next
round, not the next pass; verification takes the live-stack lock without
waiting, and is skipped and logged for that round while an e2e-test run holds it.

Those mid-pass polls run while other builds are still going, so an event can
name a unit being built. Each handler takes the unit's branch lock first, as
the build does; if a build holds it, the handler changes nothing and the
poller keeps the change to report again, which the poll after that build
finishes does. A merge still records its parent `merged` and retargets the
child's PR, but leaves the child's branch alone: the runner checks at each
step boundary whether its base has moved (`wiring.build_base_moved`), and if
so stops before pushing, back to `planned`, and its resume restacks it onto
the new base. A rewritten base stops a build the same way: a merge restacks
any child not being built, and a grandchild building on that child's branch
keeps the same base name while the commits under it change. The runner
records its base's tip when it sets up the worktree, before any restack or
adapt, and holds at the next boundary if that tip is no longer an ancestor of
the base; a base rewritten during a resume's restack or adapt is caught the
same way, and a base that only advanced does not stop it. The merged parent's
local branch is kept while any same-repo dependent's lock is held — a build
fixes its base ref before it reads `running` — and nothing deletes it later,
since the merge event is consumed: such a branch is left behind and can be
deleted by hand.

The unit's graph (`graph/`, see [unit-graph.md](unit-graph.md)) is the
sequence; `wiring.py` binds each step to git, gh and `claude`. A value a node returns
for the checkpoint is plain data or a type on the checkpoint's allowed list: the held node
stores the state's text, never the enum, so a checkpoint holds no class path that a later
release could move. The steps:

1. **Usage guard first**, before the worktree exists, so a refusal never
   leaves a half-built unit.
2. **Worktree.** `spec/<change>/<n>` (the prefix is `git.branch_prefix`)
   is checked out under the worktree root, created on its base — the newest
   `in_review` same-repo dependency's branch, else `origin/main`. A dirty
   worktree is refused, never cleaned. A resuming unit whose base moved is
   restacked first; a conflict the resolver's two steps (the conflicting hunks,
   then the files that depend on them) cannot settle goes, in the same session
   and told what was tried, to the **adapt** step, which resets the branch, keeps the old work under a ref,
   and has the rework model port it while deciding keep/adapt/retire for each
   test the old work had that the replay left uncertain — missing from the
   tree, or present but changed; a test the replay left alone counts as kept
   without being asked about. The old work's tests are those the unit defined,
   deleted or edited inside — found from which lines its changes added or
   removed and which test each falls in — not those its diff merely passes by
   as context. The pipeline checks that accounting and the
   reviewer judges it; an incomplete one is put back to the agent, naming what
   is still outstanding, for a small fixed number of attempts before the unit
   fails with those problems on its record.
3. **Tests, commit.** One scoped `claude -p` writes the group's tests (stubs
   allowed: signatures raising `NotImplementedError`, model fields), runs lint
   and format, and stops. The pipeline commits `test: <title>`. Both this
   prompt and the next name the change's later groups — `tasks.md` is read in
   full, and an agent that has just built what a later group depends on has
   every reason to finish it too — and say why: each group is a later unit's
   own pull request, and pulling its work forward makes this one bigger than
   the plan intended. The pipeline runs the profile's fixers (no model call,
   over the unit's own files) before this commit, in a build with
   `builders.stubbed_tdd_commits` off as in a stubbed one.
4. **Implementation, commit.** A second run makes those tests pass and may
   not weaken them; the pipeline runs the fixers, then commits `feat: <title>`. A branch left
   with no commits of its own — neither step added one — is not failed
   outright; see the satisfied outcome after unit-test, below.

   **Stubbed build, per group.** With `builders.stubbed_tdd_commits` on and a
   profile that supports stubs, steps 3 and 4 run once per task group instead
   of once per unit, making one `test:`/`feat:` pair per group. The tests run
   writes the group's tests and stubs and the pipeline does not commit them
   yet: `stub_checks` runs lint, format and types over the stubs and tests
   (no test run), and only then commits `test:`. Before that check the pipeline
   runs the profile's fixers (formatters and auto-fixers, see `fix_command` in
   `toolchain-profiles.md`) with no model call, so before the tests commit, and
   it does the same before the implementation commit and before each checks-loop `fix: <title> (checks,
   round N)` commit, over the unit's own files only, so a formatter's edit is
   never what fails a check. The stub loop and the checks loop share one
   routine (`graph/check_loop.py`) for the check, the saved feedback, the fix
   round and the "changed nothing" stop. A failure is saved as
   `stub-checks` feedback and `fix_stub_checks` hands it to the builder, then
   back to `stub_checks`, up to `global_limits.max_check_rounds`; a round that
   changes nothing, or the rounds spent, stops the unit. Each commit's body
   holds the change's Why sentence and the group's "Done when". The implementation run
   then commits `feat:` for the group, and the next group starts with its own
   tests. Resume reads the branch's commit subjects and starts at the first
   group without its pair (a unit stopped in the loop goes back to
   `fix_stub_checks`). A group left with no pair when the build ends stops the
   unit, naming the first group without one. A stubbed unit whose branch holds
   no commit of its own after a group (its work was already built) skips that
   count and, after the last group, goes to unit-test and ends `satisfied` as
   a build in one piece does; a branch with commits and a missing pair still
   stops. A group whose agents left nothing to commit, in a
   unit that has commits, is recorded once the whole-repository unit tests pass:
   an empty `test:`/`feat:` pair, each commit marked `Already-built: yes`, with
   the agent's account in the `feat:` body (a test-only group has no `feat:`, so it
   gets a lone empty `test:` commit marked `Already-built: yes` that holds the account). If those unit tests fail, nothing is
   recorded and the unit stops, so a forgotten implementation still stops the unit.

   A group with no new tests, in a unit that has commits, gets an empty `test:` commit marked
   `Already-built: yes` at the end of its tests step, and the implementation then completes the
   pair: a real `feat:` commit, or an empty one marked the same way once the whole-repository unit
   tests pass. A group with real tests that already pass and no implementation change is
   completed with an empty `feat:` commit once the whole-repository unit tests pass. The stop for
   a lone `feat:` commit names it: a `feat:` commit with no `test:` commit before it is reported
   with its subject, not as a missing pair.

   **Test-only groups.** An `[e2e-test]` group is a test-only group. A stubbed build commits
   it as a single `test:` commit once `stub_checks` passes, skips the implement step for it
   and goes on to the next group's tests (or to the checks). The pair count treats that
   commit as the group satisfied, and resume counts the group done once the commit is on the
   branch. The push gate makes an exception for it: it runs no red command at that commit and
   needs no `feat:` commit after it, while an ordinary group with no implementation still
   stops the unit.

   **An e2e-test group is never joined.** Every `[e2e-test]` group, flagged or not, has a
   unit of its own: the join check refuses to put it with another group, the plan check
   refuses a plan that does, and no `Separate:` line is needed. `abk tags` warns of one
   anyway. It also warns of a backticked product path in such a group, unless the path is
   a test path, a doc, the changelog or declared by a `Support:` line.

   **The scope guard and the product-defect path.** The top of `checks` holds a guard: an
   e2e-test unit whose branch changes product code, meaning anything other than tests, test support, docs, the changelog
   or declared support is stopped before any unit-test run, with feedback from the scope
   source. The builder fixes a test fault in place; for a product fault it reports a
   `product-defect` block, which the pipeline reads without a model and turns into one
   `fix-product-defect` fix change (a `[unit-test]` group to reproduce, then fix). The e2e
   unit gets a `Needs:` on it and is held as planned and gated on it, with a resume requeue
   and its feedback cleared. The gate releases it once the fix unit is no longer waited on
   (in review or merged), and it resumes rather than reworks; this does not depend on
   `wait_end_requeue`. A unit stopped by the guard itself ends the run as failed, and its
   saved feedback is used when it is requeued.
5. **Checks, then review rounds.** Before each review round the branch has to
   pass unit-test (lint, formatting, types and the tests; see step 6): a reviewer's
   time goes on a branch that already builds. A failure is saved as feedback and
   handed to the builder with the check prompt, then unit-test runs again, up to
   `global_limits.max_check_rounds` times (3; `null` is no limit; 0 means no fix
   attempt, not no check), before the unit is `failed` with the output kept. A
   fix that changes nothing ends it too, whatever the limit. Before each
   `fix: <title> (checks, round N)` commit the pipeline runs the profile's
   fixers over the unit's own files with no model call; a round the fixers
   alone changed moves the head and is not the "changed nothing" stop. This
   loop and the stub loop share one routine, `graph/check_loop.py`. It runs again
   before every later review round with the budget started over, since a
   rework can break the build as easily as the first draft. Nothing runs unit-test after the review: a reviewer reports and the
   builder fixes, so approval leaves the branch as the checks judged it.
   A read-only reviewer (`Read Grep Glob`, `git diff/log/
   show`, and the forge's read commands, `gh pr view`/`diff` or `az repos pr
   show`; nothing that writes) judges the branch against the repo's `CLAUDE.md` and the change,
   told which round this is, how many remain and what running out costs, and
   answers JSON: `approved`, `feedback`, `findings`, `earlier`, `needs_human`,
   `follow_ups`, `escalate`, `reasoning` and, on approval, an optional
   `description` (a summary and core changes, written from the diff in the same
   reply; a malformed one is ignored and costs no round). An approval stores it
   on the unit record, a later approval replacing it; the field is omitted when
   empty, so a release older than this one refuses a record that holds one.
   The reviewer also searches for prior art: for each new function, constant,
   pattern or test helper in the diff it looks for an existing equivalent and a
   second copy in the diff, naming the existing one by file and line. A duplicate
   the change introduces or makes worse is a required finding (two copies must
   change together; done is to use or extend the existing one, or extract one
   shared function); duplication the change neither adds to nor extends is not
   reported.
   Its prompt names its angles — the enclosing function of each hunk, what each
   removed line enforced, callers and callees — and an evidence bar: each
   candidate is re-checked before it is reported. Each finding carries a file, an optional line, a summary, a
   consequence, what done looks like and whether it is required; the builder's
   feedback is rendered from the list, required first, with optional findings
   past five left out (logged) and a required one without a consequence marked
   as having none. A required finding blocks approval whatever `approved`
   says. Each round records its findings with ids (`round.n`) and the commit it
   judged; the next round is shown every earlier required finding whole with
   the builder's answer, and answers each by id in `earlier` (`fixed`, `open`,
   `declined`) — it cannot approve while one is open or unanswered. A note too
   long for its budget leaves out whole findings, reported-fixed first, and
   says how many. A review that follows a person's comments is also given
   those comments, quoted, each with the builder's reply or `(no reply)`, and
   asked whether the work meets what each meant; an unmet one is a required
   finding. The comments are kept in their own field until the push, so a
   resumed run builds the same note. A reply in the earlier prose shape (no `findings`, no
   `earlier`) still works unchanged. It is told the same boundary as the build: a
   finding whose fix belongs to a later group is reported as belonging there,
   not required of this unit, while it keeps its full reach — find everything
   in one pass, sweep the domain — over this unit's own groups. An unreadable
   reply is a rejection. A `follow_ups` entry kinded `optional` approves
   alongside it and is recorded against the change, for the change's next unit
   and the PR to see; a correctness problem, a test that would pass regardless,
   a missing test a task asked for, or anything the command policy forbids is
   never deferrable and blocks approval whatever `approved` says. Rejected
   feedback goes to a rework run, which commits and accounts for each point;
   the next round is judged by the runtime's `rework_review` model and shown the earlier
   rounds. A reviewer that finds another instance of a kind it cannot
   enumerate, or that still disagrees after the builder declined a point once,
   sets `escalate` (`class` or `disagreement`) with its `reasoning`, and the
   unit is `held` for a person instead of spending another round. Up to
   `global_limits.max_review_rounds`; when the budget is spent with blocking work
   still outstanding, the branch is pushed, its PR carries the open points, and
   the unit is `held` rather than failed. A rework may mark a point `BLOCKED:`
   when its environment refuses the edit (a protected file, a permission); if
   every remaining required change is blocked, the reviewer sets `needs_human`
   and the unit is `held` for a person. Approval records the commit SHA.
6. **Unit-test.** Lint scoped to the unit's diff, then the tests of the members
   it touched (see [toolchain-profiles.md](toolchain-profiles.md)). A failure
   is kept as feedback, so the retry is one scoped rework rather than a
   rebuild (`abk requeue --rework`; a plain requeue resumes at this check and
   meets the same failure). It runs before review (step 5) and not after it.
   For a repo whose `changelog` setting is on it also runs `abk changelog
   check`, which fails a changelog with a conflict marker, bullets run together
   or repeated, a bullet outside a section or headings out of order (a repo
   with no changelog file yet passes with a note). The convention is the
   `## Changelog` section of the built repository's own AGENTS.md, else its
   CLAUDE.md, else the framework's packaged text; the build, rework, test-writing
   and restack resolver prompts carry it, and the reviewer is told not to raise
   the changelog's form or wording. A repo with `changelog: null` gets neither
   the convention nor the check. `abk init` writes the convention block, the
   changelog file and the `merge=union` rule into each such repo (see
   [init.md](init.md)), and `abk doctor` warns where the rule is missing.
   It runs only where the branch is judged on it alone or has changed since:
   for a unit that produced nothing, and on a branch moved cleanly onto a new
   base, before the push. A move with conflicts goes through the resolver's
   steps and, if they fail, the adapt step,
   which accounts for its own tests, and back through the checks and a review. A unit that reaches here with no commits of its own — its groups
   were already implemented, by a predecessor that worked ahead — is judged on
   this check alone: unit-test passing makes it `satisfied` rather than `failed`,
   its groups ticked and its dependents released, with no PR opened; unit-test
   failing still fails it. If a rework finds this — a unit already holding an
   open PR discovers its work has landed elsewhere in the meantime — the
   reason is posted on that PR before it is closed: the groups it covered, that
   they were implemented elsewhere, and the predecessor they landed in when the
   graph can say. Composed mechanically, the same as the PR body, and never
   asked of a model; a post or close that fails is recorded and leaves the unit
   satisfied regardless — a stale PR is a nuisance, not grounds to revisit a
   judgement the branch and the checks already settled. Judged on the branch
   and the check, never on what the build step reported about itself. Before
   that PR is closed, whatever is stacked on the unit leaves it as it would
   leave a merged one: the same function moves each dependent onto the unit's
   own base (its open predecessor, or the trunk), retargets its PR, tells a
   running thread rather than rebasing under it, and hands a conflict to the
   adapt step. A dependent that cannot be moved is logged, left and recorded
   in the unit's note, and the rest still move. The unit's own worktree and
   branch go last, once its run has left the tree, by the rules a merged
   unit's removal follows: the branch stays while a dependent builds on it,
   is held for depth or was not moved off it.
7. **E2e-test**, for `e2e-test` units, unless the repo's `e2e_before_merge` is `deferred`:
   then the routing skips this step (after review, at an approved tip, after a clean move),
   takes no e2e lock, and the unit records its e2e state as `deferred`; `verify` runs the live
   tests after the merge. A deferred e2e result is not green evidence: the verdict holds such a
   unit at `light` unless `review.auto_land.allow_deferred_e2e` is true. A scheduled
   whole-suite run is never skipped. A rework or an adapt (any new head the agent writes) clears
   the stored e2e state, so the state always belongs to the head that was pushed. If the repo has `dev_stack`, the unit's
   branch is brought up on it (`script up`, `script test`, `script down`,
   always torn down) — and first, when the repo `consumes` one with a dev
   stack of its own, that repo's stack from a detached worktree at its
   `origin/<default_branch>` (the local trunk for a repo with no `origin`), never the user's own checkout. Without a dev
   stack the profile's e2e-test commands run against the live stack. Either way
   under the one `runs/e2e.lock` queue (the file names its holder, and `abk status` shows the
   holder and its age), and the result is recorded with the
   commit, the command, counts and the stack-versions command's output
   (`verify.stack_versions_command`, else the repo's `infra:` profile's; see
   [toolchain-profiles.md](toolchain-profiles.md)) for the PR body. E2e-test runs in each declared project (`projects:`), from its
   directory and under its profile, as unit-test does, and from the root when none
   is declared; it runs each member's directory with no
   collection path, so it collects what the member's own pytest
   configuration (`testpaths`) selects. A stack-versions command that cannot
   start is logged and records nothing. The result also lists every failed or
   errored test with its first failure line (`E2eResult.failures`, read by the
   profile's `parse_test_failures` from the redacted output, in the order the
   runner printed them, a line over 500 characters cut with `…`). The listing
   sits in the snapshot's fixed part above the cut output, so a description's
   size limit never shortens it and the saved feedback carries it.
   A run that starts with commits on its branch fetches its repo first (a
   failed fetch is logged, not fatal), then restacks.
8. **Check the base, address new comments, then push.** Just before the push the repo is fetched
   again and the base is worked out afresh: a parent whose pull request the
   forge reports merged, which the store has not heard of, is recorded through
   the merge handler and the unit takes its new base (a forge that cannot be
   asked is logged, and the run goes on with the base it has). The branch is
   moved onto it with the restack a run starts with, but without the conflict
   resolver: a conflict is aborted and the branch left as it was. A clean move
   re-runs unit-test (and e2e-test, for an e2e-test unit) and carries the approval to
   the moved commit. That unit-test is told the base the move left (`moved_from`) and
   classifies the move: it is scoped when no file the move brought in (the files that
   differ between the old base and the new one) is also a file the unit changes, and
   full when one is, when the unit produced nothing of its own, when the move has no old
   base, or when `global_limits.restack_check` is `full`. It logs `moved base:` with which it
   was and why. A scoped move runs lint, then the tests the unit added or changed (the
   profile's `repeat_command` over their identifiers), then the commands the profile's
   `affected_test_commands` names for the unit's files together with the files the move
   brought in, asked once with no failed identifiers; no full suite confirms it. The Python
   profile selects only from the data a full run records, which it does only where
   `checks.affected` is not `off`; elsewhere the move falls back to the full suite and the
   line says `checks.affected` is off. The run logs `moved base: ran N[ of T] tests (own a, affected b)`, `T`
   being the unit's last full run's count and left out when none is known; an empty
   selection is a pass logged with zero tests. The full suite runs instead, logged as
   `moved base: ran the full suite (<reason>)`, when the profile has no hook or answers
   nothing for a project, when a selected command cannot start or loses its selection
   tooling, when the unit's tests cannot be listed, or when a file that is not a document
   was brought in outside the projects the unit changes. A failed test in the selected
   run is run again alone and serially, as in a full run. One that passes alone is a flake
   on the moved base: it is recorded and its one fix change written, but the unit gains no
   `Needs:` line and goes on to its push. A test that fails again, or that the unit added or
   changed, holds the unit as any unit-test failure does. A full run keeps its flake rule, and
   e2e-test is never repeated or isolated. The merge handler's unit-test after
   a release is told its old base and logs the same way. In a run, a conflict, or a
   unit-test or e2e-test failure on the new base, pushes nothing and resumes the unit at its
   restack in the same run (a check's failure leaves its output as feedback). That restack is what
   resolves, under the usage gate, and review is told of it. It happens once:
   a second hold in the run leaves the unit `planned` to resume at its restack
   on a later tick, so a base that keeps moving cannot loop. A pull request
   refused because its base is gone asks the forge for the base again (a parent
   merged meanwhile gives its merged-to branch) and resumes the same way.
   A rework of a unit with a pull request then reads the pull request's notes and
   conversation again (`new_comments`): any the rework was not given, other than the
   pipeline's own, go back to `rework` as feedback and are reviewed before the
   push, and the poller is told not to report them again; a failed read is logged and the
   work pushes.
9. **Push, with a lease.** The head must be the exact commit review
   approved, or the push is refused. The push carries
   `--force-with-lease=<branch>:<sha last pushed>` (the store remembers the
   SHA across processes) or no force at all for a first push. Then the PR is
   created — or edited, on a re-push — with a body saying where it sits in the
   stack, what it assumes, and how it was verified. Where the host has stacks
   (the forge's `supports_stacks`), the PR is then registered with the host as
   part of the stack of the PR beneath it — created with both, bottom first,
   or appended — and the body leaves the order to the host, saying only
   whether the chain is linear and that it merges after what is beneath it.
   Registration is advisory: a refusal (or any error from the host) is
   recorded on the unit (`stack_refusal`), logged once, and changes nothing
   else — except that a PR the host did not stack keeps the order in its
   body, as on a host without stacks, which is never asked. Either way the
   body says when the branch no longer sits on its base. The body opens with the
   change's reason (the proposal's `Why`, cut at a paragraph to a ceiling with a
   pointer to the proposal) and what the pull request does (the "Done when"
   sentence of each of the unit's groups, then the core changes the reviewer
   last stored, at most six, each capped, shrinking to the first before the goal
   or any required part gives way; the goal alone when none), then the stack
   position, scope, assumptions and verification, then what is held and left
   for later, each follow-up once, in its located form (in the body only, the
   follow-ups file keeps every point; a bare point that names a file an
   optional finding locates is left out of the body; the review prompt asks the
   reviewer not to repeat an optional finding as a follow-up). A body over the host's
   description limit is fitted by weight, not in sequence: the e2e-test output
   (its tail kept, down to the pass or fail line) and the follow-ups (whole
   items and a count of the rest) give up room first, the reason and the goal
   last, and room a part does not use goes to the others. The `local/e2e-test` commit
   status is posted for the tested SHA (and, on a host that shows statuses on
   the pull request, on the open pull request for the branch too); the rework's replies to review threads
   are posted in those threads, signed with the commit. A reply the host does not take stays in the
   unit's pending replies and is posted on a later pass, once (a reply the host already holds counts as posted). A satisfied
   unit's pull request that cannot be closed is recorded as `close_pending` and closed by each
   round until done, its reason posted once; `abk status` lists both. The unit is
   `in_review`, and its groups are ticked in `tasks.md` — now, not when a
   build finished.

A unit put back from `running` again and again with the same cause is counted by the store and
named as looping (`abk status`, the tick's log, `(looping)` in the ready queue); the notice is
visibility only and holds nothing.

Between steps the unit can be stopped: a same-repo parent went back for
rework (the unit `planned`, with cause `upstream_went_back`), or the usage window filled.
A parent that builds nothing (`BUILDS_NOTHING`: `unplanned` or `retired`) holds no one: the
check, the follow pass below and the room rule skip it as the scheduler's wait does, and
`link_needs` drops a stale stored dependency on one (`dropped dependency`).
In each round, after the fetch and poll, a unit in review is likewise set back to `planned` with that cause
while a same-repo predecessor's branch is changing (a commit beyond its pushed head, rebasing, or
itself planned for a changing upstream or a moved base; a predecessor that builds nothing is never
changing). It keeps its approval, branch and pull
request, and restacks onto the predecessor's new head when it is released. The move is an
`upstream_changed` event delivered to the unit's thread, which records it and stays waiting at
`await_review`; the release is unchanged. A unit with no thread is written to the store directly. The server's unit
summary and the `abk.units` gauge read the stored state; `status` carries the derived name.

Every change that stops a unit, holds it or sends it back (and a merge, a close, a
release, a failure) records a `cause`, a fixed set of values, on its history entry; the
note beside it is prose for people and no code reads it. The entries for starting a run,
reaching review and being satisfied carry none. A cause is one of two kinds, and the
two sets (`STANDING_CAUSES` and `EVENT_CAUSES`) together are exactly the members of `Cause`.
A standing cause names a situation that lasts until a state change passes another cause: `rework`,
`base_changed`, `upstream_went_back`, `usage`, `depth`, `toolchain`, `review_escalated_class`,
`review_escalated_disagreement`, `needs_human`, `reviewer_hold`, `gated`, `restack_conflict`,
`restack_deferred`, `restack_handed_back`, `dirty_worktree`, `attached`, `host_unavailable`,
`network_unavailable`, `service_unavailable`, `environment`, `split_held`, `manual_step` and
`too_big_for_tier`.
An event cause names a transition that has happened and is over: `requeued`, `released`,
`adopted`, `merged`, `auto_landed`, `closed`, `retired`, `superseded` and `failed`. Recording an event cause ends a standing
one explicitly. A state change the store makes on its own account (a replan's demotion and
promotion, a vanished change, a join) passes `KEEP` and so carries a standing cause forward,
with the previous note, and marks the entry `carried`, while a caller's state change passes its
own cause or none. `cause_since` of a stored unit is the time of the entry that set the cause, so a
carried entry does not restart a backoff while a second parking does. The one place a cause is
not carried is a label hold, a known gap. `upsert` keeps a unit's runtime fields, its saved
requeue and its parked splits among them, so a gated or parked unit stays parked across a replan.
A `running` unit with a thread that holds no branch lock and no lease is gated by `gate_resumable`
before a round resumes it while a merge edge is unmet; it keeps its thread and resumes once the
edge is met.
A pass lets a unit it already
built back in only when it was sent back for rework or its base changed (resuming restacks
it, so what held it is gone), or when it was parked because the code host, the network or the
model service could not be reached, once its backoff has
elapsed (1, 2, 5, 10, then 30 minutes by consecutive parking); a
unit put back for any other cause waits for the next pass, and the tick log says which cause. A unit held for depth keeps the branch it is
still on as `held_base`, and who holds it as `held_by`. A record with no cause is one from before causes or one an event ended,
and one with a cause this release does not know reads the same way: the pass never readmits it, and `abk status` lists it.
A usage pause leaves the unit `running`, with its thread interrupted before
the agent node; the first tick the usage guard allows resumes it from there.
A run that is killed is resumed the same way, at the node it was in: nothing
requeues it and nothing commits what it left.

**The size hold and the split.** With review enabled, the verdict's size step compares a unit's
changed lines with the ceiling of the tier it earned times one plus `review.ceiling_buffer`. Over it,
the review node holds the unit at once, after any round: `held`, cause `too_big_for_tier`, held by
size (`HeldBy.SIZE`), with the request (tiers, drivers, lines, ceiling) kept on the unit. A unit held
by size raises no card; a tick step asks the planner to split it into pieces with ids `<unit>-s<k>`.
`UnitStore.supersede` then writes the pieces and closes the old unit with the cause `superseded`
(`closed` with a `superseded_by` field) in one write, after keeping the old branch under
`refs/spec-driven/superseded/<unit id>`. Where a split cannot happen the unit is held again for a
person.

**Builders are told to reuse before they write.** One packaged, language-neutral part
(`reuse_guidance.reuse_guidance`, `templates/reuse-guidance.md`) is appended to the full
prompts for writing tests, implementing, fixing checks and reworking after review or
feedback: search for an existing helper, constant, pattern or fixture first, write shared
logic once, give calls that change together one function, use the shared test support,
delete what the change makes dead and stay within the change. It says how to look (what
neighbouring code imports, shared-code modules, the test runner's support places, the
language's or common conventions, search by behaviour as well as name) and reads nothing
from the repository. A continuation prompt does not repeat it, so in a reused session it
appears once, in the prompt that writes the tests; a node that starts a new session gets it
in its full prompt. The adapt prompt keeps its own instruction not to re-implement what the
predecessor provides. The rework prompt also tells the agent to look for the others of the
kind, and the tests prompt points to the shared fixtures.

The tests prompt also decides before it stubs a named function: after searching, an
existing function that does the job is tested through (no stub, "reused X instead of
adding Y" in the summary); one that nearly does it has its missing behaviour tested and no
new name created; with no helper and two places needing the logic, one stub at the shared
place covers the helper and the tests cover each call site. New tests go in files in which
every test fails, since the red check runs whole files and rejects any that pass; a
conversion with no new behaviour is tested by observing the call site reach the existing
function. The implementing prompt and its continuation (and no other continuation) let the
agent delete a stub that duplicates existing code and repoint the test with the same
assertions, saying so in its summary; "Do not weaken or delete a test" stays. The reviewer
counts a stub added by the tests commit, and a repointed test is not a finding.

**Long command output goes to an ignored file.** Every worktree carries
`.abk/out/`, named once in the repository's local `info/exclude` (never a tracked
ignore file), so `git status`, `git add -A` and the leftover commit never see it.
Each agent run gets its own empty folder in it, `.abk/out/<run>/`, and is told
where in `ABK_OUT`. The build, rework and resolver prompts carry one packaged
text (`scratch.output_convention`): redirect a long command and its exit status
into `$ABK_OUT/`, read the file with `tail`, `grep` or `sed -n`, never run a command
again to see more of it, run the suite once per round and only the failing tests
after a fix. The command policy allows a redirect into a run's folder and refuses
one onto a tracked file or anywhere else in the worktree. The folder is removed
when the run ends, however it ends. While it goes, a file past a size cap is
cut in place to its tail behind a marker every few seconds, so a runaway command
cannot fill the disk; a writer holding the file open with a plain `>` leaves a
sparse hole of NULs on its next write, which the next pass drops. One a killed run left is removed when its
unit next starts a run or its change is archived. The folder is the agent's own:
a reviewer starts with an empty one and is told to run its own commands, and
unit-test always runs the suite itself, so one agent's output never reaches another
agent or stands in for unit-test's run.

### 4. Polling and events

Which host answers is a forge's business (see
[code-forges.md](code-forges.md)); every forge is reached through one retry layer that
repeats a call by the kind its operation declares, and raises `HostUnavailable` when the
host stays down; everything below is written in the typed
values a forge returns, not in any host's JSON. A forge opens a pull request,
posts a status and answers a review comment; it also closes one — the one
call the satisfied outcome above needs, and nothing else does. Azure DevOps is
reached over typed REST through the same HTTP transport as GitHub, which is
reached over its REST and GraphQL APIs through `githubkit` (`forges/transport.py`,
`forges/azure_models.py`, `forges/github_models.py`). A poll starts no `az` or
`gh` process: GitHub's listing is one GraphQL query per page, and Azure's reads
are bounded by a request pool rather than a process count.

Nothing here is reachable from the internet, so `gh_poller.py` polls
one listing per repo instead of taking webhooks, and only for branches with
the agent prefix. Each poll diffs against a snapshot (`runs/prs-<repo>.json`)
and **acts only on a change**; the first poll of a repo records without
dispatching. Two failed polls back off for thirty minutes.

An event reaches its unit by **repo and number together**. Pull request numbers
are per repo, so two repos in one workspace reach the same one; each poller's
events carry the repo it polled, and a number that only another repo's unit has
matches nothing.

A pass polls between builds, so a change can name a unit whose build holds its
branch lock. Its handler then changes nothing: the event is **deferred**, and
the poller keeps the change to report again on a later poll — in practice the
one after that build finishes. The handlers' own writes to a repo's `.git`
(deleting a branch, removing a worktree, a restack's rebase and push) take the
repo's turn (`runs/locks/repo-<repo>.lock`), as a build's worktree add and push
do, since git's own locks there fail rather than wait. A restack takes the turn per phase: for the rebase up to its stop, and again for
its continuation or abort, the branch update and the rerere cache write; never
while the conflict resolver edits files, so other units' worktree adds and pushes
proceed meanwhile. A unit's own restack in a run follows the same rule. A branch
that moved while the resolver worked is moved again once, then held. A branch with
no worktree is moved in a temporary worktree on no branch, so the repo's own
checkout is never switched. Its unit-test run happens outside the turn.

| Change seen | Event | Effect (`events.py`) |
|---|---|---|
| `mergedAt` set | `merged` | unit `merged`; children in the same repo restacked onto their next open parent (or `main`) — a child being built only has its PR retargeted, and its build holds at the next step and restacks itself when it resumes; a merge only cascades within `global_limits.stack_depth_rebase_cap`: a child deeper than it is `held` with its depth and the cap on its record and the merged branch is kept, and a later merge in the same repo restacks it once its depth falls within the cap (the branch kept for it is left behind afterwards, like any other leftover local branch); a child being built is not held: it is retargeted as above; the merged unit's worktree removed (refused if dirty) and its local branch force-deleted — GitHub squash-merges, so `-d` would refuse — unless a same-repo dependent holds its lock, when the branch is kept. Deferred while the merged unit itself is being built. |
| closed without merging | `closed` | unit `closed`; nothing cascades to what was stacked on it. Deferred while the unit is being built. |
| label `agent-hold` added | `hold` | unit `held` (`held_by` `reviewer`), taking over a hold for depth, which a merge would otherwise free, and keeping that hold's note so it can be found again; a hold the review loop or the toolchain made keeps its cause. Nothing automatic touches it again, and the label stays until a person removes it. Deferred while the unit is being built. |
| label `agent-hold` removed | `release` | a unit the label held returns to `in_review` and its thread resumes with a release; a depth hold the label took over goes back to being one (`held_by` `depth`, with the `held_base` it kept) while its depth is beyond `global_limits.stack_depth_rebase_cap`, or, when a merge during the label brought it within, is restacked from the branch it was still on (a thread is resumed at `prepare`); a hold the review loop, a depth cap or the toolchain made (`held_by`; a record without one is not read from its note) stays held and the log says so. A comment or failing check that arrived during the hold is not recorded as seen with the release, so the next poll delivers it. Deferred while the unit is being built. |
| a check the host cancelled (GitHub `CANCELLED`; on Azure DevOps a build policy whose build ended `canceled`) that was not cancelled at the last poll, or one first seen already cancelled | `rerun_checks` | the forge is asked to run the cancelled checks again, with no agent: a cancelled check says nothing about the commit, so it is not a failing check and raises no rework. The count is on the stored unit against its last pushed commit and starts again when the head moves; past `global_limits.max_check_reruns` (default 2) nothing is asked for and the log says the host keeps cancelling the checks. A re-run check that then fails is reworked as any failing check is; a poll that finds both cancelled and failing checks dispatches both events. |
| label `agent-rework` added, `reviewDecision` becomes `CHANGES_REQUESTED`, a new comment or submitted review id, a newly failing check, or a pull request that becomes unmergeable (on Azure DevOps, `mergeStatus: conflicts`; an undetermined answer, which the host gives for a while after every push and whenever the base moves, is not a conflict and dispatches nothing; the snapshot keeps the last definite answer through it, so the conflict it resolves back into is not new; a conflict that stands after the unit's own push is offered again each poll as a `conflict` event, and the handler holds the unit, `held_by` the review loop, once `global_limits.max_review_rounds` attempts at one base tip have not cleared it or an attempt left the head unchanged). A PR first seen already red or already unmergeable is dispatched too. | `rework`, carrying the kind that sent the unit back (`failing_checks`, `conflict`, `label`, `changes_requested`, `comment`) | what the unit is handed is chosen by that kind and never by the reason's text, and the feedback is saved with its source (`review`, `ci`, `conflict`, `unit-test`, `e2e-test`), which picks the fix-the-checks prompt. The reviewer's words (review bodies, inline comments still attached to a line, the latest comment) become the unit's feedback and it returns to `planned`; for failing checks the feedback is the failed jobs' logs (from the run's jobs, the tail up to the last error); for a conflict it is the conflict alone, and the restack at the start of the run does the rebase. A held unit does not take it: the comment stays new, is delivered as a rework once the unit is released, and the wait is logged once. A comment on a satisfied unit, or on a pull request with no unit, is consumed. Deferred while the unit is being built. A rework asked for by the `agent-rework` label also takes that label off once acted on, so it can be given again; a label that will not come off is left and acted on once. |

**Labels on a pull request** are two families. The `agent-` labels are
instructions a person sets (`agent-hold`, `agent-rework`); the pipeline reads
them and never writes them, except to take `agent-rework` off once it has
acted on it — so the same rework can be asked for again. `agent-hold` is a
standing state, not a one-off request, and stays until a person removes it.
The other family is the pipeline's own record of a unit: a **state label**
(one at a time, replaced whenever the unit's state changes, written by
`UnitStore.set_state` so no call site has to remember) and a **change label**
for each change the unit carries (one, unless it joined groups of other
changes), put on once when the pull request is first recorded and left alone
after. The state names and colours are the unit graph's — one
vocabulary (`vocabulary.py`) that both read, the colour being the node's
outline — so renaming or recolouring a state changes both. `merged`, `closed`,
`unplanned` and `satisfied` carry no label: the host shows the first two
itself, and the last two have no pull request of their own to carry one. When a
unit reaches one of them and has a pull request, every state label comes off it
(`StateLabels.clear_state`: one `labels_on` read, then only the state labels
found are removed; change labels and a person's labels stay), so a merged pull
request does not keep saying `in-review`. Pull requests that were already stale are cleaned
by a step of each round, after the poll and the replies (`pipeline/label_sweep.py`): at most
`global_limits.label_sweep_per_tick` finished units' pull requests per round, lowest number first within
each repo, each recorded in `labels-swept.json` in the state directory (under a lock, replaced
atomically; losing it costs one more pass) so it is not visited again. A failed clear is not
recorded and is retried. The sweep is a step of a round, and a tick that finds no work
runs no round, so an idle installation takes its stale labels off when its next work arrives,
not before; a clear that keeps failing therefore never keeps a tick from going idle.
Labels are cosmetic and are never read back: the unit store is the source of
truth, a pull request wearing a stale label does not change its unit, and a
label that cannot be written is logged and changes nothing about the unit.
Azure DevOps keeps labels (it calls them tags) but no colour or description, so
a state is told apart by its name there; state labels, change labels and the
removal of `agent-rework` work as on GitHub. A host that keeps no labels says
so once per store and once per poll ("this host keeps no labels"), not as a
failure on each state change. A state label is written when the unit's own
state changes, so a dependent's derived state (`blocked`, `paused-rework`) is
refreshed on its own next transition, not when its parent's changes.
`agent-rework` added to a held unit's pull request is ignored and removed all
the same.

A pull request is also a **draft** while its unit is `running` or `planned` and
published when it is `in_review`, written from the same state-change hook; other
states leave it alone, and a refused write is logged without touching the unit.

A stored `running` unit is shown as `rebasing` (its last event was a conflict or
a moved base) or `reworking` (it is answering review or check feedback), or `paused` (a
pause is in force and no run holds the unit), else `running`. These are derived
from the unit's record, never stored, and `abk status`, the graph and the state
label show them. A `paused` unit resumes by itself when the pause lifts.

The pipeline's own posts — restack notes, rework replies — carry a hidden
marker and their ids are recorded in `runs/own-posts.json`, so the poller does
not send a unit back for answering itself, and a rework is never handed its
own summary as review. The ids of a person's comments a rework was given and
addressed before its push are kept apart, in `runs/given-comments.json`: the
poller skips them too, but they are never read back as the pipeline's own.

A review made in the web UI is a second comment source for the same poller
(`pipeline/ui_review.py`): each unit's threads and replies are added to its
pull request's comments under `ui-` ids that cannot collide with a host's, and
its latest decision becomes the review decision unless the host already says
changes-requested, which stands (`approved` merges nothing).
Each Request changes also adds one `ui-decision-<round>` comment holding its
summary, so a second request in a later round is news although the decision
was already changes-requested. When a rework is dispatched, the review it is
handed (`build_fetch_review`) is the host's notes, the UI's threads and replies
as notes at their lines (`ui_review_notes`, placed at the branch tip), and the
summaries of the requests for changes; `build_fetch_comments` reads the same
set, so a UI comment made while a rework runs is not lost. Every note carries
the diff hunk of the unit's own patch holding its line (`attach_hunks`), and
the rework prompt prints it under the `[comment id] path:line — body` line with
the commented line marked `<- comment`; a line the diff no longer holds has
none. The rework's replies to a UI comment are not posted to the host:
`build_post_replies` hands them to `ui_reply_writer`, which writes them into
their thread, marked as the pipeline's and left out of the comments the poller
sees, and they are never owed.

**Git's own words** are read in one place, `pipeline/git_output.py`: a failed
push and rerere's replay notice are decisions only git's text can give, and
callers take its typed result. `push_with_lease` runs `git push --porcelain`
with `LC_ALL=C` and `LANGUAGE=C` (a translated git would break every match),
and `git_push_outcome` reads the refused-ref line on stdout into one of three
kinds: `stale_lease` (`[rejected] (stale info)`, the only one that raises
`StaleRemote`, meaning someone else pushed the branch), `rejected_by_remote`
(a hook, branch protection or a non-fast-forward: the remote's answer, raised
as a plain `RuntimeError` carrying what the remote said) and `other` (anything
else, such as an unreachable remote). `replayed_files` reads the
`Resolved '<path>' using previous resolution.` notice from a rebase's stdout and
stderr together, since git writes it to stderr. The contract tests
(`tests/pipeline/test_git_output.py`) run against output recorded from real git
in `tests/fixtures/external/git/*.txt`, each headed by `# tool: <git version>`,
`# command: ...` and `# returncode: N`, then the `--- stdout` and `--- stderr`
sections. When a git upgrade changes its wording and one fails, regenerate them
with `uv run python tests/fixtures/external/record_git.py`: it builds temporary
bare remotes (a pre-receive hook, a branch that moved under a lease, a missing
remote) and a rerere replay, runs real git, redacts only paths and commit ids,
and rewrites the files. Review the diff, then adjust the adapter.

**Restack** (`restack.py`) moves a child branch with
`git rebase --onto <new base> <old base>`. Its git invocations carry
`rerere.enabled=true` (never written to the repository's own configuration,
so an operator's own checkout is unaffected unless they turn it on
themselves), which reuses a conflict resolution recorded restacking one unit
when the same conflict recurs restacking another — the cache lives under the
repository's common git directory, shared by every worktree of it, so
anything an operator resolves there with rerere on locally feeds the same
cache the pipeline reads. `autoUpdate` stays off, so a replayed resolution
lands in the file but the path stays unmerged and unstaged until something
stages it deliberately. A conflict — replayed or not — is handed to a scoped
Claude run that is told both sides' intent (both are planned units) and which
paths arrived with a replayed resolution, and that works in an order: the
conflicting hunks only, then — when a check fails — the unit's other files that
depend on the conflict, then a port. The checks run between the calls (no
markers left, the moving unit's own tokens still present, none of its own tests
missing), and a failed check is named in the next call. Files edited beyond the
conflict are accepted and named among those resolved. Leaving a replayed file
unchanged accepts it, editing it replaces what's cached for the next replay, and
planting a `<<<<<<<` in it rejects the replay: that forgets the cached entry so
the next sibling sees the conflict fresh, and fails the step's check, so the
second call follows instead of the move aborting. What two steps leave
unsettled goes, in a run, to the `adapt` port in the same session, told which
steps were tried and what their checks said; the stack-move handler leaves it
`planned` with cause `restack_conflict`, and the lane's same worker goes straight on into that run, which starts the
order from its first step. After a clean move
whose diff (`git patch-id`) is unchanged and whose head review had approved,
unit-test runs again and the branch is pushed with a lease and a "Restacked"
comment. Anything else — a resolved conflict, a changed diff, a head review
never approved — goes back to `planned` to be reviewed before it is pushed.

Registering a chain as a stack on the host does not hand it the rebasing: the
host has no API to trigger its own cascading rebase, so the pipeline still owns
`restack`. The host may rebase and force-push the branches above a stack merge
itself, though — every branch above, not only the merged PR's direct child.
So every push first reads the branch's head where it is pushed (the restack
does too): one that no longer holds what the pipeline last pushed was moved by
someone else. Its head is adopted — the local branch brought to it, with any
unpushed local commits replayed on top, and recorded as the last push so the
next lease holds — the old approval is dropped, and the unit goes back through
review before anything is pushed.

What the host holds is compared with the local branch by what each changes over
the repo's trunk (the diff id). If it is the same change in different commits —
a message edited, or an older restack of the same work — nothing is adopted: the
host's head is recorded as the last push, the approval stands, and the approved
head is pushed with a lease on it. Otherwise the local commits are replayed on
the host's head. When the local branch still descends from the last push, the
commits after it are replayed, which keeps a squashed predecessor's commits out;
when a restack means it no longer descends, the commits the host lacks by patch
(`git cherry` over the trunk) are. Either way a commit the host already holds by
patch is skipped. If the replay does not apply, or the worktree has uncommitted
changes that adopting would discard, the push stops with `StaleRemote` naming the
host's head.

### 5. Post-merge verify

Once every unit of a change is `merged` (or `unplanned`), `verify.py` deploys
what the change's PRs touched and runs the live tests they added — under the
e2e-test lock, since both use the one live stack:

- the changed paths of each PR (`forge.pr_files`), per repo, in
  **deploy order**: a repo after the ones it `consumes`;
- **deploy conventions before rules**: test and documentation paths deploy
  nothing; a change in a workspace library member counts as a change in every
  member that declares it as a dependency; then the first `deploy.rules`
  entry whose prefix matches decides, and a path matching nothing deploys
  nothing. Each command runs once, from the repo's own checkout, which must be
  on its default branch and clean (paths in `deploy.live_written` excepted)
  and is fast-forwarded first — a dirty checkout fails the verification rather
  than being pulled into;
- commands whose first word is in `deploy.agent_for` run inside
  `ssh-agent` holding `deploy.ssh_key` when `needs_ssh_agent` is set, for
  image builds that fetch a dependency over SSH;
- **live tests as the consumer**: the `tests/integration/` files among the
  changed paths, selected by `tests.e2e_marker` and excluding
  `tests.dev_stack_marker`, run per member with the process environment plus
  `verify.env` (each value resolved by its provider now) plus the repo's own
  credentials (`deploy.credentials`: names from a shell array in its dev-stack
  script, values from its `.env`). "No tests selected" is not a failure.

The outcome is recorded in `runs/verified.json` with the merged unit ids it
covered; the same units are not verified twice, and a change that gains a
merged fix is verified again. A failure is kept for a person — nothing
retries — and `abk verify <change>` reruns it once the cause is fixed.

### 6. Archive

`openspec archive <change> --yes` folds the change's delta specs into
`openspec/specs/`, so those specs describe current behaviour rather than
intentions. It runs only when every unit carrying a group of the change merged
(a change whose groups another change's unit carries waits for that unit too)
**and** verification passed,
in merge order (two changes touching one requirement conflict when the second
archives), and never twice. A conflict is not auto-resolved, and it does not end the
tick either: the failure is logged with its reason, the change is skipped, and the next
tick tries it again. A finished change with no directory is logged as withdrawn and not attempted.

## Cutting and fitting text

`budget.py` is the one place text is cut to a size. `cut_head`, `cut_tail` and
`cut_middle` take a text, a size, a boundary (`char`, `line` or `paragraph`) and a
marker: each returns the text unchanged when it fits and never returns more than the size.
A head cut (keeping the start) closes any code fence or `<details>` block it leaves open;
a tail cut (keeping the end) opens again what the dropped head left open, with lines of its
own that it keeps within the size. A cut keeps whole pieces of the next finer boundary
(paragraph, line, character) when no whole piece with content fits, so a text with content
is never cut to nothing. `forges.base.fit_description` is a wrapper over `cut_head` with the
description note as its marker; it is the last guard of the description builder.

The description is fitted once, to `forges.description_limit()`, the lowest description
limit across the registered forges, where the open-pull-request step builds the body; no
forge cuts a description it sends. `build_pr_body` makes the body from `Section`s and
shares the limit with `fit`: the Why and the goal weigh eight, with their smallest forms
(the Why's pointer to its proposal, the goal whole) reserved first, the Why capped by its
ceiling; the position, scope, assumptions, restack note, held points, footer and the e2e-test
results are required (the results shrink to their pass or fail line and a note that the
output was trimmed, the output keeping its tail), and the follow-ups, whole items followed
by a count, weigh twice what the output does.

`fit` shares a budget between `Section`s (a render function, a natural size, a smallest
honest form, a weight, an optional ceiling and whether it is required). Everything is
rendered in full when it fits; otherwise every section gets its smallest form (dropping
from the lowest weight up, never a required one), the rest is shared by weight, and a
section needing less than its share keeps only what it needs and passes the remainder on.
A render that overshoots is trimmed from the section with the most room and rendered again
(up to three times), and a final line cut guarantees the budget. Ties go to the earlier
section, so the result is deterministic.

The same module builds three other texts. A unit's e2e-test output is one section per
command (4,000 characters in all): a passing command keeps the end of its output, up to
1,500 characters, and a failed one weighs four times as much and keeps, for each failed
test, its identifier and the end of its own section (where the error is) before the end of
the rest; a profile that cannot read the failed tests keeps the end of the output, as
before. The earlier review rounds a reviewer is shown are sections too: open findings and
round headings are required and kept whole however long, findings already fixed or declined
are left out whole (fixed ones first, each oldest first) with a count, and only when none is
left to leave out are a round's prose and the builder's responses reduced. A commit status description is
fitted to `forges.status_limit()`, the lowest `status_limit` across the registered forges,
where `e2e.post_status` builds it; no forge cuts it.

## The guards

None of these rely on the prompt being followed. All three read as they do
because Claude Code is the default runtime; the hook contract and the usage
window are its own. The `acp` runtime, when selected, is not held by the usage
window (`cmd_tick` in `cli/pipeline.py` and `wiring.build_may_start` skip it),
and it enforces the command rules through client capabilities and permission
answers instead of the hook. The details are in
[agent-runtimes.md](agent-runtimes.md). A proposed layer under all of them, a
kernel-enforced sandbox for agent steps, is in
[sandbox-design.md](sandbox-design.md).

**The policy hook** (`hooks/policy.py`, `pipeline/command_policy.py`). Every
agent run passes `--settings` registering a `PreToolUse` hook for `Bash`,
`Edit`, `Write`, `MultiEdit` and `NotebookEdit` — per run, never in the user's
global settings. It denies: every registered forge's way of merging — `gh pr
merge`, `az repos pr update`, `az repos pr set-vote`, `az repos policy` and the
raw `az rest`/`az devops invoke` escapes, the union rather than this repo's
host; `git commit --amend` (it would fold
the implementation into the tests commit); `git reset --hard`, `git clean`,
`git branch -D`, recursive `rm`; a push that lands on `main`, `master` or any
branch a repo's `default_branch` names — judged by where it lands, so `HEAD:dev`
and a delete (`:dev`) count — since those are reached through pull requests;
bare `--force`;
any force-with-lease on a branch without the agent prefix; a bare
`--force-with-lease` without an explicit `<branch>:<sha>` or
`--force-if-includes` — a bare lease compares against a remote-tracking ref a
fetch in the same command may already have advanced, which is how one tool
overwrote a concurrent commit while reporting success. Commands are split on
`&&`, `||`, `|`, `;` and newlines and stripped of wrappers (`xargs`, `env`,
`sudo`, `timeout`, ...) before the check. File writes must stay inside the
worktree the run is in (temp files outside any checkout excepted), and the
planning repo's specs directory — readable through `--add-dir` — is read-only:
a build agent may not tick its own tasks. A hook that errors would fail open
in Claude Code, so every unexpected path here denies. The same commands are
also passed as `--disallowedTools`: two independent things have to fail
before an agent can merge its own PR.

The guards by class: a location guard (the hook's worktree check and specs fence, the command
rules' fence on the planning repo's `abk.yaml` and `abk.local.yaml`, ACP's command-text fence)
stands down when the step is confined, because the sandbox refuses the write; it is what runs
when a step is not confined. A guard about meaning (the merge, push, force-push, commit and
`--no-verify` rules, `planning_paths`, the redirect rule) stays in both modes. `abk policy check`
and `abk status` list which is which from `runtimes/guards.py`; the table is in
[sandbox-design.md](sandbox-design.md).

**The config guard** (`config_guard.py`). `abk.yaml` and `abk.local.yaml` are read before an agent
step and after it. When the step was not confined a difference fails the unit with
`ConfigChanged`. During a confined run a person may edit them: with coverage `process` or
`files` the step could not have written them, so the difference is a warning with its diff,
shown by `abk status`, and the unit continues. The track runner passes no coverage and still
fails.

**The usage guard** (`usage_guard.py`, `pause.py`). The account is a
subscription with a usage window shared with the user's own sessions, and
credits past the plan limit cost money. No new unit starts once a window is
at its threshold; the reading comes live from the usage endpoint with Claude
Code's stored OAuth token (kept in `usage-cache.json` for a time that adapts, and never past a
window's reset). The time starts at `usage_cache_minutes` (fifteen by default); each refusal doubles it up to
`usage_cache_max_minutes` (thirty minutes by default); a refusal naming a retry time of zero asks for no wait and leaves it alone; a longer retry time a refusal names is respected; and each quiet
stretch of that time halves it, never below the configured value. It is worked out from `usage-calls.jsonl`, and
`abk status` shows the time in use and what set it. A rate-limit answer starts a cool-down kept with that file, a timeout is retried
once, and a failed call uses the last good live reading younger than `usage_fallback_minutes`
(thirty by default, source `cache`) as read, then Claude Code's own cache when it is under an hour old. **An unknown reading pauses.**
**A refused or unreadable read does not pause while the reading kept leaves ample room.** When
the endpoint cannot be asked (a refusal, a cool-down, an error, or the minimum interval) and the
guard's own cache holds a last good reading of any age, each window is estimated as the figure
read plus what has been spent since the reading. Where the cost basis is adopted for a window
(`usage_estimate_basis: cost`), the estimate adds the recorded cost of every ledger row at or
after the reading, rows with no unit included, times a learned points-per-dollar figure (plus an
hourly intercept where `usage_estimate_intercept` is on); a unit allowed on an estimate that has
no cost recorded yet counts the flat per-unit allowance instead, once. Otherwise the flat basis
applies: an allowance for each unit that has spent since the reading or been allowed on an
estimate since (`estimate_units` in the cache file, kept under the refresh lock), counted once
by unit id. The cost fit is made over pairs of readings with cost recorded between them (at least
`usage_cost_min_pairs`, quantile `usage_cost_quantile`) and adopted only when it has fewer false
allows than the flat figure over the same gaps; it is kept in `usage-allowances.json` as version
2. The flat allowance is calibrated: each tick derives it from pairs of consecutive good
readings in `usage-calls.jsonl` and the units that spent between them (the ledger) as the 90th
percentile of points gained per unit over the newest thirty pairs, rounded up, between a floor
(one) and a ceiling (the number set as `usage_unit_allowance_pct`, else twice the built-in ten
or two), and only from eight pairs; the result is kept in `usage-allowances.json` beside the
cache file, and `abk status` prints it. Until then, or with `calibrate_usage_allowances: false`,
the configured allowance (ten points for the session, two for the week by default) stands. A
window that has reset since starts from zero at its reset plus the most it could
have climbed since (the climb floor and margin), so a long outage stops being covered. A start
is allowed while, in both windows judged apart, the estimate plus `usage_headroom_margin_pct`
(five) is under that window's threshold; otherwise it pauses as before, and the reason names the
estimate. At most `usage_estimate_max_starts` (three) units start on one reading; a good read
drops the list and the count. A reading at the plan limit, or with credits enabled and a window
full, and Claude Code's own reading are never the base, and a reading younger than the fallback
age is used as read with no estimate; a raised `usage_fallback_minutes` is no longer needed to
keep work moving. Only a start that happens is recorded: the gate before an agent step names its
unit, a track names itself, and the round's decision, the resume time and `abk status` start
nothing and record nothing. The risk left is the person's own use of the account, and any other
consumer the guard cannot see, while the endpoint is out of reach; the margin and the cap bound
it. `abk status` prints the same estimate line from the reading held, with no call, when that
reading is older than the time a reading is kept and the endpoint cannot be asked.
**A pause never ends before it is written:** the grace after a reset is added
once, in `pause.py`; a reset time already past is treated as unknown (retry
after thirty minutes); and a reading too old to trust refuses starts for the
stale-retry interval (`usage_stale_retry_minutes`, five by default) without
borrowing its window. A reading served from the cache file has its own source,
so it is not mistaken for a live one.
**Claude Code's own cache is read before the endpoint is asked.** When the block
`cachedUsageUtilization` in `~/.claude.json` was fetched (its `fetchedAtMs`, never the file's
modification time) within `usage_claude_cache_minutes` (the cache time unless set; 0 turns the step
off; never more than an hour), describes both windows, has none past its reset, and is fresher than the
guard's own kept reading while that is fresh (a tie is the guard's), the guard decides from it with no
call, even inside the minimum interval, and `abk status` shows it. The reason ends
`(claude.json, 6m old)`. It is only a reading: never written to the guard's cache, never an
estimate's base, no cool-down. The block carries no credits state, so the credits rule does not
apply to it; the thresholds decide. Only interactive Claude Code use refreshes it (which actions do has not been
established beyond that), so headless runs find it old and the order is unchanged. Past its window it remains the stale fallback for a failed call.
**The usage module is the only authority.** Every run (tick, pass round, gate, tracks, status)
asks it, and it alone decides whether to call the endpoint. At the expiry of the cached reading
one process refreshes, reading the cache, calling and writing under a non-blocking lock on
`usage-cache.json.lock` (the cool-down is read under it too); any other asker finds the lock
held, is served the last good reading (source `cache`, whatever its age, while its window has not
reset) and does not call. The cache file is written whole, so a reader never sees half of it. A
reading is never used past the reset of a window it describes, from the cache file or the editor.
The pause marker is a record: a usage marker refuses nothing, the guard is asked every round and
clears it when it allows, and only a `rate_limit` marker (the model's own refusal) stops a pass or
makes a tick report "paused", until its deadline, worked out again each round. A step that began
under the threshold finishes; the next gate refuses. The cache is counted as `abk.usage.cache`
with an `event` of `hit`, `miss`, `expiry` or `wait`.
**Every use of the endpoint is recorded** (`usage_calls.py`) in `usage-calls.jsonl`, beside the
cache in the state directory and gitignored: one line per call or cache answer with the time, the
caller (`guard`, `status` for the runtime's usage status, `cli-status` for the status command, `tracks`), the outcome (`ok`,
`rate_limited`, `timeout`, `error`, `cache` or `claude-json`, the last for a decision answered from
Claude Code's own block and not a call to the endpoint), the status, the latency, the rate-limit and
retry headers of the answer and, for the cache and the block, the reading's age. It holds no token, keeps a week, and
archiving a change leaves it. From it `abk status` prints one line (calls in the hour, refusals,
the cache's share, the block's share and the shortest interval between successful calls that no refusal followed
within a minute), and the figures are exported as `abk.usage.calls` by outcome and caller and the
gauge `abk.usage.safe_interval` in whole seconds, drawn from the record when the metrics store is
down.
**A step already running is never interrupted** — the guard only ever gates
what starts next, and a step that ends having written nothing is not judged against the window.

**The usage forecast** (`usage_forecast*.py`, beside the estimate and its cap). Before a start is allowed
the guard forecasts what it will cost in points of each window: a unit by the history of its review
tier (the chance that each step runs, bounded at `usage_forecast_quantile`, times its mean cost, over
the tier's units once there are `usage_forecast_min_runs` of them, else the window's flat per-unit
allowance, the prior), a track or the planner as one call at its mean, plus what running units still
have to come and the tracks and plan call due before the window resets. The forecast is added to the
estimate and the reading is checked again with it; a refusal names the window, the forecast and the
step with the most points. When a unit's first step is admitted, a forecast row is appended to `usage-forecasts.jsonl` in the
state directory, and a step row for every step (once per node and round); `abk report --by tier`
compares them with the spend and `abk status` prints a `forecast:` line from them. `usage_forecast: false` decides as before.

**The endpoint is asked only when a fresh reading could change the decision** (`decide_start`).
Every tick, round and gate asks the guard, and the guard decides whether to call. Usage only
rises within a window and falls when it resets, so a refusal on a reading of a window that has
not reset stands without a call (the pause ends at the reset, or when the rising threshold is
worked out to reach the reading), and an allowance stands, however old the reading, while the
most usage could have been added since it (the fastest climb per window in points a minute seen in
`usage-calls.jsonl`, no less than `usage_climb_floor`, times the minutes, plus
`usage_climb_margin_pct`; readings closer together than the cache time are not paired) leaves it under the threshold. A reading with less headroom than that,
one of a window that has reset, or none, needs a fresh one, and the endpoint is not asked more often
than the cache time: inside it the start is refused for the time left, with a reason that says so.
The per-unit gates, the resume time, the tracks' start check and the round all decide this way, so a held reading that settles the decision keeps working while the endpoint is down. A round asks for no reading on behalf of units left out of it by `--only`, a lease or a backoff, unless a change is still to be planned.
`abk status` prints the held reading with its age and source and calls nothing unless given
`--refresh`, which is still held to the interval.

The two windows do not share a threshold, and a threshold need not be flat:
quota unused when a window resets is lost, so a window with a ceiling above its
pause percent (`usage_pause_ceiling_pct` over `usage_pause_pct`, in each of the
`session` and `weekly` sections of `runtimes.claude_code.limits`) ramps from the
one to the other over the last `usage_relief_fraction` of *that* window — the session
against the five-hour reset, the week against the seven-day one. A ceiling left
out is the pause percent, and a window whose two are equal does not ramp: the
ramp is skipped, not computed flat. The ceiling is validated below 100, so
relief never reaches the point where credits pay.

In the usage guard every account uses one path: the default account is an explicit value (`Account.default()`), and
the credentials, state file, expiry check, token read, login refresh and doctor check are one
implementation for it and for a labelled account. A labelled account's files are named
`<name>.<label>.<suffix>` (`usage-cache.<label>.json`, `paused.<label>.json`); the default
account's keep the unlabelled names, and its cache has no `account` key.

A pause is kept per account: it writes `runs/paused.json` for the default account (a network
outage, which holds every account, has `runs/network-paused.json` of its own) and `runs/paused.<label>.json` for a named one, with the
account recorded, a deadline, a reason and a kind. The
deadline is the moment the ramp would clear the current usage plus
`runtimes.claude_code.limits.<window>.usage_resume_buffer_pct`, else just after the window resets, else
thirty minutes later when nothing says when, and never more than six hours out.
It schedules nothing: the tick timer already runs every few minutes, and a
paused tick asks the guard again, so the first tick the guard allows clears the
marker — whether the ramp got there, the window reset, or someone raised the
threshold. The one exception is a pause the model itself caused (a rate-limit
refusal): the usage endpoint can show room it has just refused, so that pause
is kept to its deadline without asking. A `claude` call refused
mid-unit with a rate-limit message pauses too; a `claude` killed by a signal
leaves the unit `running`, and the next tick resumes its thread at the node it
was in.

A third kind, `network`, is written when a unit parks as `network_unavailable` (never for
`service_unavailable`), with the reason `network unreachable during <unit>`; a later parking
while it stands does not move its time. It is the probe's to end: each tick asks the control
group (the code hosts and `global_limits.network_control_hosts`) first, and the first tick in which
a host connects clears the marker, whatever its deadline, while a probe that cannot run counts
as reachable so a broken probe never holds it. While it stands the tick stops what a usage
pause stops (starting units and planning) and still polls and records; it logs and `abk
status` shows `waiting for the network — <reason>`.

**The push gate** (`gate.py`, `commit_order.py`, `red_check.py`,
`check_runner.py`; `abk gate`). A branch reads as tests-then-implementation
pairs: the first substantive commit is tests (plus stubs with no logic —
checked with `ast` for Python), no two tests commits in a row, at least one
implementation commit. At each tests commit, in a throwaway worktree, lint
and format pass with type checking skipped, and the new test files run
**red for an accepted reason**, read from pytest's JUnit report (the console
is a logged fallback when no report could be read): an assertion or
`NotImplementedError`, or a missing module or attribute raised inside a test
body, or a fixture raising `NotImplementedError` at setup. A test module that
fails to import at collection is rejected, so the tests commit adds stubs for
what its tests import; so are a syntax error, a missing fixture and an
empty run. Each test file is judged by the profile of the project it belongs to, with that
project's clean and red commands run in its directory; the repo's profile covers files outside
every project, and the gate fails if any project fails. Results are cached by patch-id so a
restack does not re-run them. In a stubbed build a test-only (`[e2e-test]`) group's tests
commit is the exception: no `feat:` commit follows it, it gets only the clean command (lint,
format and types) and no red run, and its result is cached under its own mode; a unit made
only of test-only groups needs no implementation commit. The gate accepts an
empty pair marked `Already-built: yes` after a real one, and it accepts an empty `test:`
commit marked the same way before a real `feat:` commit, or a real `test:` before an empty
`feat:`; a restack keeps them and the squash merge drops them. A stray branch is repaired by
resetting to the group's previous `feat:`, cherry-picking the empty `test:` with
`--allow-empty`, then the real `feat:`.
This is the command form of the rule, for a person or a hook; the runner's own
push condition is the approved-SHA check above.

**A rejected commit is a fix round before it is a failure.** The target repo's
own commit gate (its pre-commit hooks) runs on every commit the pipeline makes.
A rejection is retried once as is — a gate that rewrote the files has already
fixed them — and then the gate's own output, file, line and rule as it printed
them, goes to the build run's agent in the same worktree under the same tool
policy, for a bounded number of rounds. Every attempt commits everything with
the hooks on: no skipping flag, no narrowed set of paths. The agent may not go
around it either: the command policy refuses `--no-verify`/`-n`, `SKIP=`,
`HUSKY=0` and any `core.hooksPath`, and a fix round that moves HEAD itself —
however it did it — fails the unit rather than reading as nothing to commit.
A gate that never accepts fails the unit with its last output on the unit's
record. One fixer serves every commit a unit makes, reworks included, and the
fix rounds are not checked against the usage guard: at most two short runs per
commit of a unit already under way.

**Nothing reaches a PR unreviewed.** The runner pushes only the commit the
review loop recorded as approved; a restack that left the diff byte-for-byte
unchanged carries the approval over, and any other rewrite — a resolved
conflict, work from a run that stopped before its verdict, a rework's own
commit — is reviewed again first. Uncommitted work is committed *before* the
reviewer looks, never after approval. The reviewer cannot edit: judging and
authoring are separate processes with separate tools. (On the `acp` runtime
that is kept by refusing what the agent asks permission for, plus failing the
run on any change to the worktree — docs/agent-runtimes.md.) A unit whose rounds ran
out is pushed too, but never past this gate: it is the commit the last round
reviewed, not one exempted from review — it is just not the commit that round
approved.

### Tests that cannot hang or race

- **A command limit.** Every command unit-test runs has a time limit,
  `global_limits.unit_test_command_seconds` (an hour by default), far over what a suite takes. A
  command past it is sent SIGABRT in its process group, so a runtime that can dump the
  stacks of its threads does; one that ignores that is killed after
  `global_limits.unit_test_abort_grace_seconds`. Unit-test fails with the command, the time
  ("timed out after N seconds") and the end of its output, dump included. This catches a
  run whose tests all pass and whose process then does not exit.
- **A test time limit.** `tests/time_limit.py` fails a test that runs past
  its limit from a timer thread, in setup, call and teardown alike: `--test-time-limit` (sixty
  seconds) for a test without the `local_stack` marker, `--e2e-test-time-limit` (thirty
  minutes) for one with it, zero turning either off. A test without `local_stack` marked
  `time_limit(<seconds>)` gets that many seconds in place of `--test-time-limit`; a
  `local_stack` test keeps the e2e limit even with the marker. The marker is for a test whose
  time is outside its control, such as a download. The failure names the limit and its kind;
  the run goes on (see `docs/agent-runtimes.md`, Test markers).
- **A test time split.** `tests/time_split.py` reports where a `local_stack` test's time went.
  For each phase of a test that requests the `scratch_ledger` fixture (the scratch
  installation's usage ledger) it reads the rows appended since the last phase on that
  ledger, so a module fixture's rows fall in the setup of the first test using it, and
  prints at the end of the session one line per phase: `ABK-TIME ` and JSON with `test`,
  `phase`, `agent` (milliseconds by role), `calls` (by role), `checks_ms` (spans with a
  command, environment setup included), `other_ms` (the wall time left, never negative)
  and `overlap` (true when the parts sum above the wall time). The e2e-test result merges the
  lines by test and phase and shows them beside the entry; a test without the fixture
  gets no line.
- **A guard.** `tests/timing_hazards.py` parses the test tree and fails on a bare sleep, a
  function that makes a thread and neither joins nor signals it, or a fixed port, except in
  the shared helpers and the files on its allowlist. The allowlist may only shrink: a file
  whose uses are gone fails the guard until it is removed.
- **A wait helper.** `tests/waiting.py` `wait_for(condition, what=, timeout=)` is the one way
  to wait for a condition; it names what it waited for on timeout.
- **A step to call.** The output cap's pass is `scratch.cap_files`, idempotent (a cut file is
  within the limit and is not rewritten), and `scratch.watch_folder` yields an event set after
  each pass, so a test calls the step or waits on the signal and never polls a file.
- **A flake is isolated, recorded and fixed once.** When unit-test fails on tests, the profile's
  optional `failed_tests` and `serial_rerun_command` hooks give the failed identifiers and a
  serial command for just them, and `build_unit_test` runs that twice. A rerun that fails leaves
  the failure as it was. Both passing raises `FlakeFound`: the unit's node calls the runner's
  `on_flake`, which has `flakes.wait_on_fix` make sure, under `flakes.lock` in the state
  directory, that one open change exists for the test (a successor, `-2` and on, only after
  the earlier one is archived) and add a plain `Needs: <change> group 1` line to each of
  the unit's groups, and appends the flake to `flakes.jsonl`. The unit is held `planned`,
  cause `gated`, with a `resume` requeue waiting, so `release_gated` resumes it once the fix
  has merged: it restacks and runs unit-test again. A unit of the fix change itself does not
  wait. `abk status` lists each flaky test with its count and fix change.
- **A pre-existing failure is recorded and fixed once.** A test the base run names as failed
  is appended to `<state_dir>/preexisting-failures.jsonl` (test, unit, command, first
  failure line, time, the base run's result and output, the `split` it failed in (`rest` or a
  declared split; an older entry's `runtime` is read as the split, `base` as `rest`) and the
  fix change), through the
  same `FailureRecord` the flake record uses. `untouched_failures.ensure_fix` makes sure,
  under `preexisting.lock`, that one open `fix-failing-<slug>` change exists for the test id
  (name capped with a hash, so a flake of the same test is a different change), and writes
  it without a model: a proposal, a design stub, one `[e2e-test]` group with its tests first,
  `Priority: 1` and an acceptance opt-out, and a spec. A successor (`-2` and on, its spec
  MODIFIED, the proposal naming the earlier attempt) is written only once the earlier change
  is merged and archived. It reports `exists: <change>`, or `would write: <change>` then
  `wrote: <change>`; `abk tick --dry-run` prints the same first line for each recorded test,
  even when no unit is pending, and writes nothing. The flake fix change is also written at
  `Priority: 1`: a unit waits on either kind until it merges. `abk status` lists each as
  `pre-existing:` with its count and fix change.
- **A unit behind a fix waits, and is told only of its own failures.** When every failure of a
  e2e-test run is pre-existing, the node (`Nodes.wait_for_preexisting`) records each through the
  runner's `on_preexisting` (`wiring.build_on_preexisting`), gives each group of the unit a
  plain `Needs:` line (`group 1 — failing test <id> on the base`) and parks it as `wait_for_fix`
  does: `PLANNED`, cause `gated`, a `resume` requeue. It resumes restacked at e2e-test, which runs
  in full again. A unit of the fix change, or one with a failure of its own or broken by it, is
  failed as today; its pre-existing failures are still recorded and fixed, without a `Needs:`
  line. The feedback saved on a failure drops the lines and output of pre-existing tests
  (`untouched_failures.feedback_snapshot`) and names them once.
- **A unit about to run a full e2e-test run waits for an open fix.** Before `run_e2e`, and only
  when the runner's `e2e_runs_whole` says the run executes the whole marker, the node asks
  `on_e2e_gate` (`wiring.build_on_e2e_gate`). `untouched_failures.holding_fixes` returns
  the recorded fix changes that are open, were recorded by a unit of the same repo, are not the
  unit's own change, carry no `Needs:` from it and were recorded for a split the run executes
  (a fix for a test in a held or unexecuted split does not hold it); each gets a `Needs:` line through
  `wait_on_preexisting`, and the unit is parked as above before the stack lock or any test.
  A same-repo fix releases the unit once its unit is in review, not only when it has merged.
  A closed fix change keeps the unit waiting until a person clears it. `abk status` ends each
  `pre-existing:` line with the number of units waiting on its fix.
- **New tests are repeated under load.** After unit-test passes, the tests the unit added or
  changed (`tests_changed`) are run `global_limits.unit_test_repeat_runs` times (three by default, 0
  turns it off) with each test command's own workers, narrowed to exactly those tests (`path::Class::name`) by the
  profile's optional `repeat_command` hook (the `RepeatsTests` protocol); any failure fails unit-test with that run's output. A new test is not
  classified as a flake. The test-writing prompt and the reviewer's checklist carry the same
  determinism rules (`templates/determinism-guidance.md`): wait on events, not the clock,
  join or signal every thread, bind a free port, share no temporary path, assert no state a
  background actor repairs, and expose a step for timer code. A change that introduces such a
  use is a required finding, since the test passes alone and fails under load.

- **E2e-test failures are classified and checked on the base.** After a failed e2e-test run
  each failed test is the unit's own (its file changed on the branch, or a `conftest.py`
  beside it did) or untouched. The untouched ones are run once, together, with the
  profile's serial rerun command in a detached temporary worktree of the unit's base,
  inside the hold the unit's own run took. A test the base run names as failed or errored
  is pre-existing; any other is the unit's. Nothing is classified for a dev stack run or
  when the failed tests cannot be read. A base run that cannot be made (the worktree
  cannot be added, a command cannot start) is logged and proves nothing: the tests it
  has not named are the unit's, and the unit fails as it would without it. Each failed
  command is repeated on the base with only its own tests. The node passes the base each
  run is against, so a restack that moves it is followed. `global_limits.e2e_base_runs: 0`
  turns it off. E2e-test tests are never repeated or isolated by unit-test's machinery.
  Known limits: ids are read as relative to the repo root (or the configured project), so
  a workspace member run with `--directory` prints ids relative to the member and a
  changed file of that member is not recognised as the unit's own; and the cost of the
  clean base worktree on a large repo's own e2e-test suite was not measured.

- **A unit's e2e-test run is narrowed to its own tests.** Under `e2e_unit_scope: own` (the
  default; `global_limits`, with `tests.e2e_unit_scope` per repo; its earlier, numbered spelling
  still loads) a unit runs only the e2e-test tests
  its branch added or changed, selected by identifier together with the marker. A unit with
  none runs nothing, takes no lock and says `e2e-test skipped: no e2e test added or changed`;
  its status says that no e2e-test test ran. Only files the runner collects by default
  (`test_*.py` or `*_test.py` for python-uv) are named, so a helper module and `conftest.py` are
  not, whatever `def test_*` they hold; a custom `python_files` or `testpaths` is not read, so
  tests it adds run only in the whole marker run. A unit that touched only such files runs
  nothing, and the skip line ends with the files left out. Where the run cannot be narrowed (a dev stack
  script, a profile that cannot select by identifier, tests that cannot be listed, no base),
  or under `full`, the whole marker runs and the log says why. A scheduled unit is always
  `full`.

- **The whole e2e-test suite runs on a schedule.** `e2e_schedule` (`daily`, `weekly` by
  default, `monthly` or `off`; `global_limits`, with `tests.e2e_schedule` per repo; its earlier,
  numbered spelling still loads) makes each round, before planning and ahead of the usage
  guard, write `scheduled-e2e-<repo>-<date>-<split>` for each split of a repo with an e2e-test
  unit that is due, without a model call. The due date is read from the names of the split's
  open and archived scheduled changes, so nothing else is stored, and one such change is open
  per split at a time. `has_work` is true while a repo is due, so an
  idle installation still reaches the round. The change's unit goes from `prepare` straight
  to the whole-suite e2e-test step on the default branch: no tests, implement, checks, review,
  push or pull request, and no agent call. A pass ends it satisfied with a note and the change
  archives; a failure is recorded as pre-existing, fixed by `fix-failing-*` changes and
  waited on as for any unit. It is counted by `max_units_in_progress`, waits for the e2e-test
  lock and starts only when the usage guard admits a unit. The `scheduled-e2e-` prefix is
  reserved. `abk tick --dry-run` prints `would write:` or `exists:` and writes nothing.

## Telemetry

With `ABK_OTEL_ENABLED` set (docs/configuration.md) a tick that has work exports traces and
metrics over OTLP/HTTP, and flushes them before it returns; an idle tick exports nothing. It
never changes what a run does.

```
tick                      one per tick that has work
 └─ unit                  unit.id, change, repo, tier, outcome
     ├─ <step>            the graph's node names; step, round, outcome
     │   └─ agent         runtime, model, role, turns, outcome
     └─ …
```

The tick's context is copied into each unit's worker thread, so the unit spans of a tick share its
trace. A unit that runs again in a later tick starts a new trace with a link to its previous
run's, kept on the stored unit (`trace`). `round` is the review round of a `review` step, the fix
round of `checks` and `fix_checks`, and the review round a `rework` answers. A `rework_review`
agent is a `review` role; its model says which model judged. Spans carry identifiers, counts and
names, never a prompt, a diff, feedback, a commit message or an error's text: a failure is its
outcome and, for a failed check, its kind.

| Instrument | Kind | Attributes |
|---|---|---|
| `abk.tick.duration` | histogram (s) | outcome |
| `abk.unit.duration` | histogram (s) | repo, tier, outcome |
| `abk.step.duration` | histogram (s) | step, outcome |
| `abk.review.rounds` | histogram | repo, outcome |
| `abk.checks.failures` | counter | check (lint, test, types), round |
| `abk.agent.turns` | histogram | role, model |
| `abk.agent.tokens` | counter | two series, told apart by `source`: the runtime's (role, model, kind input/output/cache; no `source`) and the ledger's (repo, tier, node, role, model, source, kind input/output/cache_read/cache_creation). Each call is in both, so a query must select one with `source=""` or `source!=""`; summing without it counts every call twice |
| `abk.usage.pauses` | counter | kind (usage, rate_limit) |
| `abk.units.reclaimed` | counter | |
| `abk.units` | gauge | state |
| `abk.slots.free` | gauge | |
| `abk.slots.idle_with_ready` | gauge | |
| `abk.e2e.test.duration` | histogram (s) | marker, file (the test id up to `::`), phase (setup, call, teardown) |
| `abk.e2e.test.time` | histogram (s) | marker, file, cause (agent, checks, other), role (agent time only, else empty) |
| `abk.agent.cost` | counter (USD) | repo, tier, node, role, model, source (measured, estimated) |
| `abk.node.duration` | histogram (s) | node |
| `abk.wait.duration` | histogram (s) | bucket (slot, usage_pause, queue_full, lease, backoff, needs_person) |

The last three are the usage ledger's figures, exported by the recorder that writes a ledger
line: an agent record adds its cost and tokens, a span its time. A figure a record lacks adds
nothing, and with telemetry off nothing is exported. The two e2e-test histograms are exported
when an e2e-test run writes its `test_time` rows.

`abk telemetry push-dashboard` pushes the packaged dashboard to the Grafana at `ABK_GRAFANA_URL`.
`ABK_GRAFANA_TOKEN` is optional: set, every call carries it as a bearer token; unset, the calls
carry no authorization header, for a Grafana that accepts anonymous editing. A 401 or 403 on an
anonymous push is reported as a refusal that names the token setting.

Unit ids and change names are on spans only, never on a metric. Tokens are recorded where the
runtime's output carries them: Claude Code's result event, and the `usage` of an `acp` agent's
prompt response when it sends one.

## Secrets never leave as text

The set of known secret values (`verify.env`, the credential settings, the `redact` list,
each gateway key minted) is gathered when an installation is activated and held in memory
only. Text is redacted at the last step before it is stored or sent, not in each caller:
the unit store's `set_feedback`, the run log, the transcript (before a tool result is
cut), printed output (so the journal is redacted too), the usage ledger's strings, unit-test
and e2e-test output (before the 4000-character cut), the forge's write methods, and the
rework prompt as it is assembled. A value is replaced by `[redacted:<NAME>]`; one under
8 characters is not. If redaction raises, the text is replaced by `[redaction failed: text
withheld]` and one line logs the failure's type and place, never the text. The token
shapes (`sk-`, `ghp_`, `github_pat_`, `Bearer`) are heuristics for a secret nobody
configured: they miss a key with no recognisable prefix and can match a harmless string.
A secret split across two transcript events is not found. Text already saved is not
rewritten by the pipeline; the temporary `abk redact-history` does it.

### E2e-test splits

The held set is the `hold: true` entries of `tests.e2e_splits` together with the unexpired
entries of `e2e-held.json` in the state directory; the configuration wins. One function
builds a run's selection from the repo's splits, the held set and the one split to run
alone, and every e2e-test command takes it. A run records the split of each failed test
(`rest`, a declared split or `unknown`); a held split's failures are never recorded, and
neither is one whose split is `unknown`. A unit waiting on a held split is parked with the
cause `split_held`. The scheduled e2e-test run is one change per split and `rest`, named
`scheduled-e2e-<repo>-<date>-<split>`; an older change with no suffix or ending `-base`
counts as `rest`.

A parked unit follows its group's `Split:`. Each pass, after planning and before the release of
split-held units, reads the groups of every planned unit with the cause `split_held`, parked splits
and no run in flight, as `tasks.md` has them now. When they are all in one split that is not the
split the unit is stored in and not one it is parked on, the park ends once: the unit is delivered
a rework requeue (not a resume) with an automatic note that says the `Split:` changed from the old
split to the new one, that the task text changed with it and that the group's tasks are to be read
again; its parked fields are cleared and its stored split becomes the new one, so the next pass
finds nothing to do. A new split that is itself held defers the rework: the unit stays parked, and
releasing the old split does not resume it onto its old tests. A group that still says the stored
split, or says a split the unit is parked on (the backstop), leaves the unit parked, as do groups
that do not read as one split or a tasks file `abk tags` refuses. `abk status` shows a deferred
unit on its parked line, a dry run says what it would rework, and `abk replan` runs the same step
after it plans.

A unit parked on a held split can also be requeued with `--rework` (with or
without a note) or `--restart`, which deliver a rework or restart requeue, then clear the park, and the
agent runs again from `prepare`. A plain requeue is refused while a parked split is held, and a
unit with a pull request or a step on its branch is refused as any other unit is.

A group of a change declares its split with a `Split:` line, because the planner cannot know where
a test will land until it is written, and a unit must be started or left alone whole: the unit
records the one split its groups share and groups of two splits are never joined. A planned unit
that has never started and whose split is held is not started: the round leaves it out as it does
a held unit, it takes no place and lends no priority, and its wait reason is `split` ("waiting
for e2e-test split <name>"). The round that finds the hold gone starts it. A unit that has started
is not gated, and a wrong declaration is caught by the parking above, which stays as the
backstop; `abk e2e-test check` warns about a declaration that differs from a group's own tests.

### A failed live test says what its scratch tick did

A live test (`local_stack`, under `tests/integration/`) runs `abk tick` through
`tests/scratch_tick.py` and reads a unit's branch through its `commits_on_unit_branch`.
`run_tick` stamps each output line as it arrives and remembers the last three ticks of a
scratch. A branch that never reached the remote fails with a first line `cause hints:`
(the tick's return code, the pause marker, whether the branch exists, the unit's wait
reason), then the tick's output, the wait reasons, the run log tail, the pause marker and
who pushed, not with a git error.

`tests/scratch_dump.py`, listed in `tests/conftest.py` beside `tests.time_split`, adds a
`SCRATCH STATE` section to the report of a failed or errored `local_stack` test (setup,
call or teardown) that has a scratch: a fixture argument named `scratch`, the `scratch` attribute of any
fixture argument (a module-scoped fixture that builds one), or one passed to
`register_scratch` during the test. It is the last part of that test's failure block and opens with the
same `cause hints:` line. It holds, each within a cap: the last tick's output (last 6000
characters), the wait reason and the summary of each unit (20 lines of 200 characters),
the pause marker (1000 characters), the lease holders (10 lines) and the e2e lock holder (read from its file, never locked), the remote's heads (30 lines),
the tails of the decision log, the usage ledger and the run log (15 lines of 300
characters), the fake host's requests (30 lines) and the tick's environment (40 names;
a name that looks like a secret is listed without its value). One dump is at most 20 480
characters and a session's dumps 61 440; a dump that would take the session past that gets
one line saying it was left out, and only what is printed is counted. The text goes through the redactor, and the values of secret-looking
environment names are registered first; if redaction fails the dump is replaced by one
line saying it was withheld. A source that cannot be read is one line,
`scratch state unavailable: <ExceptionType>`; the hook never changes a test's outcome,
runs only `git` with a 10 second timeout, and writes nothing in the scratch.

The e2e-test result carries only the last 4000 characters of the run, so the dump reaches
a reader through the full output file the result names (`Full output:`), where it is
redacted and bounded already; the result itself carries the `cause hints:` line.

## State on disk

The planning repo's state directory (`planning.state_dir`, default `runs/`):

| File | What | Loss means |
|---|---|---|
| `units.json` | every unit: state, branch, PR, pushed and approved SHAs, feedback, history. In-run progress (review rounds, deferred follow-ups, pending replies) is in the unit's thread, not here; only `approved` and `predecessor_note` stay, because the push gate and the restack write them with no run in progress. A store whose unit still carries a value in `review_rounds`, `deferred`, `pending_replies`, `person_comments`, `resume_from` or `classic_run` is refused when read, naming the unit and the field; the empty `resume_from` and `classic_run` the last release wrote on every unit are dropped on read. A key no field of this release names is dropped on read when empty (a newer release's field carries nothing, and the next write omits it) and refused when it holds a value, naming the unit, the field and the value and saying a newer release wrote it: the value is information this release cannot keep. The truth; the graph page is a view of it. | rebuilt work. Commit it. |
| `notifications.json` | the cards shown or held back: when each was first seen, last shown and the reminder due, so a restart repeats none. | cards shown again or held again by their delay. |
| `verified.json` | the last verification of each change and the units it covered. | a change verified again. |
| `planned.json` | hash and attempt count per change's specification. | one planning model call per change. |
| `prs-<repo>.json` | the poller's snapshot per repo. | the next poll only records; events in the gap are missed. |
| `own-posts.json` | ids of the pipeline's own PR comments and reviews. | a unit reworked over its own reply. |
| `given-comments.json` | ids of a person's comments a rework addressed before its push. | the same comments reported as a second rework after the push. |
| `landing.json` | the landings in progress: one record per pull request the pipeline is about to merge, naming the repo and unit, written before the forge is asked and removed once the merge is recorded. A merged event for a pull request with a record is recorded with the cause `auto_landed`, not as a person's merge. Replaced atomically; a record that cannot be written stops the landing. The landing pass runs once per tick, after the first round's poll, and an error landing one unit is logged without stopping the others. The `acp` runtime ignores the deny lists, so only the host's server-side guard stands against a merge there. | a merge after a crash is recorded as a person's. |
| `audits.json` | the audit of each landed unit the sample picked: its class, whether it awaits a result or holds `ok` or `wrong`, and the time. Replaced atomically. | a landed unit loses its place in the audit queue. |
| `demotions.json` | the demotion of each review class: its triggers (what, which unit, when), since when, and when it was lifted. A standing demotion holds the class's units at `light` and keeps the landing step from landing them; it is never written to `abk.yaml`. Replaced atomically. | a demoted class lands again until demoted anew. |
| `verdicts.json` | the verdict of each unit after its latest review round: the class, planned estimate, classification, evidence tier, tier and reason, whether it is final (only the approving round's is), and the changed paths and lines. Replaced atomically; nothing reads it to decide anything but the verdict's history floor, which counts a class's brief-carrying records the way `abk review report` does. Each new outcome is counted once as `abk.review.outcome{outcome,tier,class}`, and each merged unit whose evidence tier was `auto` once as `abk.review.agreement{class,accepted}`; neither carries a unit id. | the record of what review would have needed. |
| `held-waiting.json` | the held units that have already logged that a comment is waiting on them. | the wait is logged once more. |
| `paused.json`, `paused.<label>.json`, `network-paused.json` | the current pause of the default account, of each named account, and of a network outage (which is every account's): whose, until when and why. | one usage check. |
| `usage-ledger.jsonl` | the usage ledger: one JSON line per agent call (see below), plus `span`, `sample` and `affected` lines (a fix round's selected run: tests selected and in all, estimated seconds saved, whether the full run agreed). Gitignored. | the spend history, not the work. |
| `decisions.jsonl` | the decision log: `{at, unit, reason, waits_on, tick}`, appended only when a waiting unit's reason (`WaitReason`) or what it waits on changes, with a `none` record when the wait ends. Read from its tail when the pipeline starts; trimmed to `retention.decision_log_mb`, newest lines kept. Gitignored. | why a unit waited, and for how long. |
| `usage-cache.json.lock` | the lock one process holds while it refreshes the reading. | never needed. |
| `usage-cache.json` | the live usage reading (kept `usage_cache_minutes` to `usage_cache_max_minutes`) and any rate-limit cool-down. | one endpoint call. |
| `e2e.lock`, `locks/` | the e2e-test queue lock; branch, repo and store locks. | nothing; kernel-released. |
| `unit-logs/<change>-<nn>-<YYYYMMDD-HHMMSS>-<step>.log` | one file per unit run: a header (unit, change, step, model, base, start), that unit's lines, then the outcome. `<nn>` is the unit's number padded to two digits, so a change's units sort in order and a unit's runs sort by time. The last three runs of a unit are kept; a log older than `retention.unit_log_days` is removed once the unit has a summary in the usage ledger (a unit without one keeps it); archiving a change removes its files. The file name and `started:` are UTC; each entry starts with the tick's own local-time `[HH:MM:SS]`, the same stamp it prints (the closing `outcome:` line has none: the line above it, the run's last, does). Agent replies and tool-call commands are written whole, line breaks kept; each further line of an entry starts with four spaces (`run_log.CONTINUATION`) and has no stamp, so every line that starts at the margin is a new entry. The journal keeps its one clipped line per step. The unit's `run_log` names its latest. Gitignored. | a unit's transcript; the tick's own output is unchanged. |
| `e2e-output/<change>-<nn>-<YYYYMMDD-HHMMSS>-e2e.log` | the whole output of each command of a unit's e2e-test run, passing ones too, appended after each command so a run that dies keeps what it had, and redacted as a whole before it is written (a failing redaction leaves the withheld notice). The result's `output_file` and its `Full output:` line name it, the unit's run log carries the same line and `abk status` shows it for a failed unit whose last result was an e2e-test failure. The last three files of a unit are kept (`run_log.RUNS_KEPT`); archiving a change removes its files. Local only. | the posted result keeps only the last 4000 characters of the output. |
| `transcripts/<change>-<nn>-<YYYYMMDD-HHMMSS>-<node>-<round>.jsonl` | one file per agent run of a unit (implement, rework, review, checks fixes) or chat turn, named like a run log plus the node and review round that made the call (round 0 outside a round). One JSON event per line, appended as the agent streams, the same shape for Claude Code and ACP: `kind` (`text`, `reasoning`, `tool_call`, `tool_result`, `plan`, `usage`, `permission`, `stop`), `at`, `unit`, `node`, `round`, `session`, `source` (`build` or `chat`), `text`, `tool`, `call` (a tool call's id, repeated by its result), `input`, `usage` and `truncated`. A tool result longer than `global_limits.transcript_result_chars` is cut there, ends with `… [cut: the result was N characters long]`, and carries the original length in `truncated`. A text or reasoning event is a whole message or thought, not a streamed fragment, and a user-side event of the Claude stream contributes only tool results. The calls of one run (a unit thread's pass, or one chat turn) share the run's stamp, and the last `global_limits.transcript_runs_kept` such runs of a unit are kept, whole; archiving a change removes its files. Local only, never committed or sent anywhere. | the agent tab's replay of a unit; the run log is unchanged. |
| `<run id>-<repo>-<track>.md`, `tracked-issues.md` | the tracks' run logs and issue tracker. | history the tracks read. |

The tick commits nothing. The template `.gitignore` excludes only the locks,
`.env`, `.last-runs/` (the tracks' raw output), `unit-logs/` (the unit run
logs) and the usage ledger; `units.json`, the tracks' run logs
and the graph page (`planning.graph_page`, rewritten on every store write) are
meant to be committed by the operator, and the pipeline commits the tracks' run
logs and `tracked-issues.md` by path after each phase. Unit worktrees live under the worktree
root — `~/.local/share/<planning dir>/worktrees` unless configured — and the
planning repo's `.env` holds machine-local settings.

#### The three roles of a planning root

A planning repo is **separate** from the code repos, or it is one of them (a repo in
`abk.yaml` at path `.`). `planning_mode` tells which of three roles a root has:

- **separate**: no repo shares the root's git repository. The pipeline keeps it on its
  default branch (a stray branch is kept and reported; a rewritten default branch stops
  the run). A tick checks the default branch out before reading state; the tracks also
  pull it with `--ff-only`, as before.
- **working copy**: where a person works. The pipeline never changes its branch, files
  or index. When a pipeline worktree is live, `abk status` and `abk doctor` there name its
  path and print `abk --config <worktree>/abk.yaml <command>`, and `abk tick`, `abk track`,
  `abk verify` and `abk archive` refuse (exit 2) unless a config is named with `--config`
  or `ABK_CONFIG`. With no live worktree they run as before.
- **pipeline worktree**: a detached worktree outside the repository, made by
  `abk install-timers`. The path is recorded in the marker `abk-pipeline-worktree` in the
  common git directory, which every worktree shares and which is not in the tree.
  `--remove` removes the marker and leaves the worktree.

Before a tick or track the pipeline worktree is synced to the tip of the default branch
(`origin/<default>`, else the local branch): equal is current, behind is a fast-forward,
ahead is logged and the run goes on. An unfinished merge, rebase, cherry-pick or revert,
a stray branch, a divergence or a merge git refuses stops the run with one
`planning sync stopped: <reason>` line and exit 1. Nothing is stashed or reset; a file is removed only when the incoming commits hold it
byte for byte (a published planning file that has landed).

What is committed is limited to the planning paths (specs directory, state directory,
the two pages and `abk.yaml`): planning commits are path-limited, verify's dirty check
excludes the planning paths and refuses on anything else, and a unit worktree's file
tools may not write them (the fence). `locate` answers with the pipeline worktree's
`abk.yaml` when run from a unit worktree. `planning.publish` decides whether the
tracks' commits are pushed to the default branch (`direct`) or to a
`planning/...` branch with a pull request (`branch`).

### The usage ledger

The ledger also holds `span` lines (a wait is one with `waited` set to its reason and no node;
a review round carries a `cause` of `review`, `check` or `conflict`) and, each time a running
pass refreshes, one `sample` line with the counts of units `running`, `in_review`, `blocked` and
`queued`, the `free_workers`, the `limit` and the `cap`. Readers skip a kind they do not know.

An e2e-test run also writes one `test_time` line for each phase of each test its toolchain timed
(`unit`, `change`, `marker`, the full `test` id, `phase`, `duration_ms`, and `agent_ms`,
`checks_ms` and `other_ms` when a test suite reported the split). The toolchain profile asks
for the durations (`parse_test_durations`; none for a toolchain that prints none), and a line
of the form `ABK-TIME {json}` with `test`, `phase`, `agent` (milliseconds by role), `calls`,
`checks_ms` and `other_ms` is merged onto the entry of its test and phase. `E2eResult.durations`
holds the entries slowest first; the posted result opens with the three slowest and lists the
first `global_limits.e2e_durations_shown` of them (0 lists all) above the output, so cutting the
output never drops the listing.

`<state_dir>/usage-ledger.jsonl` gets one line for each agent call a unit's graph makes, when the
call ends, ok or failed (a Claude Code call cut off by a usage limit included). A line names
where the call was made (`unit`, `node`, `round`, `change`, `repo`, `tier`), what ran (`role`,
`model`, `runtime`), the `session_id` and whether the call `resumed` one, the figures
(`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`,
`turns`, `duration_ms`), the `cost` object and the `outcome`. A figure the runtime did not report is
absent, never zero, and `usage_source` says where the figures came from: `gateway` (the totals
a gateway logged for the call's own key, see below), `reported` (the
runtime's own: a Claude Code result event; an `acp` prompt response's `usage` and the cost of its
last `usage_update`, in USD only), `estimated` (declared; nothing produces it yet) or `none`.
The `acp` protocol advertises no usage capability at initialize, so an agent that never reports
usage and one whose payload was unreadable both read `none` (the latter is also said once in the
run's log).

Writes are best-effort: a record that cannot be kept (no workspace loaded, the state directory
unwritable) is dropped, never fails a run, and is reported once per process for each reason. The
reader (`usage_ledger.read_ledger`) keeps the last line for each unit, node and round, the session id being an attribute of the
line and not part of its key: a node run again counts once, and a call that continues a session
another node started (`fix_checks` continuing the build session) is that node's own spend, so one
session id can appear under several nodes. A call with no session id cannot be told apart from
another and stays a record of its own. A resumed call keeps its session id and
its record holds that call's figures, not a running total, so a `resumed` line adds to the call of
the same node and round it resumed instead of replacing it, adding only `incremental_usd`.

A call made outside the unit graph is recorded too, through the same helper
(`pipeline/call_record.py`) the unit's steps use. Its `node` is one of `OverheadNode`
(`pipeline/vocabulary.py`): the conflict resolver writes `restack`, with the unit being
moved as `unit`; the planner `plan`; a track phase `track_<phase>`; init `init_research` and
`init_propose`; the login refresh `login_refresh` (no figures,
its output is discarded); a chat turn `chat` and the attach flow's fix turn `chat_commit`, with the
unit the session is attached to. The reader keeps every row of a node outside the unit graph's
call nodes (`tests`, `implement`, `review`, `rework`, `fix_checks`, `adapt`) as a call of its own,
whatever its session, so two resolver calls for a unit both count. A blank `unit` means the call
belongs to no unit; it is spend, and the usage estimate and its calibration never count it as a
unit. `abk report` shows such calls, one line per node, under `pipeline overhead` in the by-unit
view; a `restack` row has a unit and stays on it. `tests/test_agent_call_guard.py` fails on an
agent call that records no row; its allowlist is empty.

The `cost` object holds the call's own spend (`incremental_usd`), the session's running total as
the runtime reported it (`cumulative_usd`), `basis` and, where a gateway's figure is recorded
instead, the runtime's own incremental figure (`reported_usd`). `basis` is one of `reported` (the
runtime gave the call's own figure), `derived` (the difference of two cumulative figures),
`first` (the session's first call, baseline 0), `unknown` (a resumed call with no known
baseline: no incremental figure, never the total), `backfilled` (a row repaired once from a running total) or `legacy`. A running total
(a Claude Code result's `total_cost_usd`, an ACP `usage_update` amount) becomes an increment
against the session's previous total, kept on the recorded `AgentSession` and, failing that,
read from the ledger's last record with the same session id; a total below the baseline starts a
new baseline and is logged. A gateway-attributed call records the gateway's figure as
`incremental_usd` and the session's running sum as `cumulative_usd`. A line written before the
object, with a flat `cost_usd`, is read as `legacy`: the figure is kept as `legacy_usd` and never
summed. Every cost total, the summaries written at archive, the web UI's usage view and the
`abk.agent.cost` counter add `incremental_usd` only. The counter is right from the release that
introduced the object; figures exported before it counted a session's earlier calls again in each
later one.
The `context` object says how full the model's window was, in tokens: `used_start` (the fill
at the call's first request), `used_end` (at its last: input plus cache read plus cache creation),
`added` (their difference, never below zero), `peak` (the largest fill at any request),
`compactions`, `max` (the window) and `basis` (`reported`, `estimated` or `unknown`). Claude Code's
fill comes from each `assistant` event's usage (a request repeated by its content blocks counts
once; a sub-agent's requests, which name the tool call that started them, are not the main
context); the window is the result's `modelUsage[model].contextWindow` for the model the
conversation ran on (read off its `assistant` events; the result keys its entries by full model
id and may list background models too), else `runtimes.claude_code.context_windows`, whose
figure is recorded with `basis` `estimated`. An ACP agent's fill is its `usage_update`s' `used` and `size`;
an update carrying neither figure (zeros) is no figure. A resumed session starts from the figure
the agent replays on loading it; that replay is assumed, so an agent that replays none starts the
step at its first update. A compaction is the
runtime's own marker (Claude Code's `compact_boundary` event) where the stream has one, else a
fall in the fill between requests larger than `context.compaction_drop_share` of the window. A
figure the runtime does not give is absent with `basis` `unknown`, never zero, and never fails a
run; a step ending above `context.warn_share` of the window logs one warning and nothing is
scheduled from it. Rows written before this have no `context` and cannot be rebuilt from retained
transcripts, which hold only each call's aggregate usage. The gauges `abk.agent.context_used` and
`abk.agent.context_max` and the counter `abk.agent.compactions` carry the cost's attributes.
With `ABK_GATEWAY_URL` and `ABK_GATEWAY_MASTER_KEY` set, each agent call of the graph gets a
gateway key of its own, aliased `abk:<unit>:<node>:<round>:<random>` and handed to the agent in
`ABK_GATEWAY_KEY` (`AgentRequest.env`). When the call ends the figures the gateway logged for that
key are read and recorded with `usage_source` `gateway`, the agent's own report is kept beside
them (`reported`, `cost.reported_usd`) for a report to compare, and the key is revoked however the
call ended. A gateway that cannot be reached, a refused mint or unreadable totals is said in the
unit's log once per call and the call goes on as without a gateway: no key, and the agent's own
figures as before. A gateway writes its spend logs in batches, so the read repeats until the rows
have stopped growing for `ABK_GATEWAY_QUIET_SECONDS` (10, at least the gateway's flush interval),
bounded by `ABK_GATEWAY_SETTLE_SECONDS` (30); rows still arriving at the bound are used and the log
says the totals may be incomplete, and a key with none says so and the record keeps the agent's
figures. The gateway's `prompt_tokens` is recorded as
`input_tokens` and includes cached input, which the rows do not break out, so a `gateway` record's
`input_tokens` can exceed the agent's `reported.input_tokens` by the cache. Only calls with an
attribution place and a result callback get a key. The seam is `pipeline/gateway_usage.SpendSource`.

#### Archive roll-up

When a change is archived its detail lines become one `kind: summary` line per unit: the unit's
totals and a `breakdown`, one item per node, role, model and usage source, ordered by that key.
Waits and checks have no role or model and sit in an item of their own for the node (role and
model `(none)`). The roll-up checks that the items sum to the totals before writing, and rolling a
change up again merges items by key and gives the same line. A summary without a breakdown, from
an older ledger, still loads and totals and reads as one `(archived, no breakdown)` row in the
node, role and model views; merged with new detail it becomes one item under that label.

#### Spans

The same file carries `kind: span` lines, stretches of a unit's time stamped in UTC with
`started`, `ended` and a monotonic `duration_ms` (`pipeline/spans.py`; a test replaces
`spans.clock`). Each has the `unit`, `change`, `node` and `round` it belongs to, an `outcome`,
and for waits a `waited` bucket:

| span | written by | `waited` |
|---|---|---|
| a node's run | the graph's node wrapper, when the node returns or raises (`outcome` is its status, or `error`) | empty |
| the wait for a build slot | the tick: from the unit's being ready while every slot was taken to its worker taking the branch lock | `slot` |
| a usage pause | the gate, once the guard lets the paused node start: from the interrupt (stamped in its payload, so a later process measures it) | `usage_pause` |
| a unit-test command | `build_unit_test`, one per command, under `command` | empty |

Recording is as best-effort as the agent lines and shares their once-per-process report. The
usage reader skips every line that is not an agent call.

#### State files

A state file (the unit store, the pause marker, the planned hashes, the notification store, the
ledgers a command rewrites and the like) is written by `atomic_write_text`
(`pipeline/file_lock.py`, beside the file lock): the text goes to a temporary named for the
process, which is renamed over the file last and removed if anything is raised, so a reader never
sees half a file and two writers never share a temporary. A writer that holds the file lock takes
it around the call. A test fails when another module replaces over a file from a temporary name.

#### Shared helpers

`abk init`, the commit gate and the scaffold run git through `pipeline.shell.git`, as the modules
that already did. The restack module keeps its own wrapper for its conflict-memory flags. Callers
that take an injected runner (verify, the wiring's commit, init detection) or run in the hook
process build their own git argv. Where a change lives comes from `changes_dir_under(root,
specs_dir)` (`installation.py`), which `Installation.changes_dir` also uses and from which the
pull request body derives its repo-relative link. The host-address pattern
(`forges/github.py`) and the diff-hunk pattern (`pipeline/own_tests.py`) are each defined once and
imported.

#### Metric records

The same file carries `kind: metric` lines, whether or not telemetry is on
(`pipeline/metric_records.py`). Each is written by `emit_metric`, which makes the telemetry call
and the record in one step (no other code calls `record_metric`; a test enforces it) and which the
metrics page's catalogue reads like a direct telemetry call. A record carries the
instrument's `metric` name, its `value` and its `attributes`, plus the `unit` and `change` it
belongs to where there is one (an exported metric never carries them):

| `metric` | written when | `value` |
|---|---|---|
| `abk.tick.duration` | a tick ends | seconds |
| `abk.unit.duration` | a unit's run ends | seconds |
| `abk.review.rounds` | a unit's run ends other than paused | the review rounds it took |
| `abk.checks.failures` | a unit-test run fails | 1 |
| `abk.usage.pauses` | a pause for the usage window or a rate limit begins | 1 |

Durations and counts are the very figures given the instruments, so a total derived from the
records equals the exported one. The archive roll-up leaves these lines as they are, and the usage
reader skips them. Recording is best-effort like the rest of the ledger.

An `acp` agent's `thoughtTokens` are not read: only `outputTokens` is recorded, and whether it
includes reasoning tokens depends on the agent. Move the ignore line if `planning.state_dir` is changed.

## The web server

`start_server(installation, agent_environment=...)` hands every agent the chat starts (a turn, a
new or continued session, the resume check) that mapping as its whole environment, so a test
can keep its own process's variables out of them; `abk serve` passes none.

`abk serve` (`serve/server.py`) is a FastAPI app on uvicorn, bound to `127.0.0.1`. Its
readers are library calls over the same stores the tick uses, and read only: the unit
store is parsed without write hooks, the ledger is read by line (an unparsable last line is
skipped), run logs are tailed by byte offset, and the checkpoint database is opened
read-only, never created. The log's host-local `[HH:MM:SS]` stamps are converted to UTC from
the header's start time. Usage is the report builder's output unchanged, so the server and
`abk report` cannot disagree.

The UI is a single-page app in `web/`, built by Vite (with Tailwind) into
`serve/static/` inside the package; the wheel carries it through hatch's `artifacts`
because the build output is git-ignored. `create_app` serves a file from there when the
path names one and `index.html` for any other path outside `/api`, so client-side routes
load on a direct visit; an unmatched `/api` path stays a JSON 404, and with no build a
page answers 503 saying how to build. The review endpoints (`serve/review.py`) are the
server's only writes: a unit's diff is `git diff` from where its branch left its base to
one resolved commit, and its threads, replies, summary and one decision per round are kept
in `reviews/` in the state directory, each thread anchored to the commit it was made at and
placed at the branch tip when read. The approve action and `abk approve` are one function,
`approve_unit`: it records an approval decision (`approve`) for the round with the pull request's head
and never merges, pushes or votes on the host. The pages are described under `abk serve` in
[cli.md](cli.md).

### Chat

The agent tab and the sessions page write through `serve/chat.py`; the rest of the server
only reads. Each turn is one agent call whose recorded events go through `serve/bridge.py`
(`AgUiEncoder`, `messages_snapshot`) to the browser as AG-UI events over server-sent events.
Every run opens with `RUN_STARTED` and ends with one `RUN_FINISHED` or `RUN_ERROR` carrying the
thread and run ids; the tests check each event against the `ag-ui-protocol` models and the
order of the whole stream. The prompt of a chat turn, with its attachments, is recorded in the
unit's transcript as a `user` event, so a reloaded tab shows the question before the answer.

- A running step is streamed from its transcript and takes no input. The tab's stream keeps a
  read position per transcript file, so pruning an old run never shifts what a live step
  sends, and opens each run it sees with its own `RUN_STARTED`.
- Once the step has ended, the first turn takes the unit's lease (`pipeline/lease.py`, files
  under the state directory), and only then checks that no step is running or holds the
  unit's branch. `ready_units` and `resumable_units` leave leased units alone, so a tick
  starts nothing on them, and a build that takes a unit's branch lock reads the lease again under it: the server writes the lease and then reads the lock, the build takes the lock and then reads the lease, so one always sees the other. A lease names the process that took it, so one left by a server
  that died holds nothing. It is released explicitly, or when the tab's event stream closes
  and no turn that tab started is still running: a turn is never left editing a worktree the
  tick has taken back.
- The lease is also the attachment. Its record holds the holder, the process that took it
  and when that process started, plus the checkouts the chat covers, the number of files
  those checkouts hold uncommitted (recorded after every turn), the session and runtime, the
  branch head when it was taken, and a marker for a commit made and not yet delivered. A
  record written without the new fields reads as before. A lease whose process has gone
  and which holds no changes and no marker holds nothing, as it always did; one that holds
  changes or the marker is a *stale lease*: it stays, no process holds it, and it is
  resolved by a person. Closing a page releases only a lease that holds nothing; a lease with
  changes stays and refuses `DELETE /lease`. A server that starts takes over every stale lease
  with changes (holder `server`); the first page to chat, or to discard, takes it from there.
- A chat attaches only while the unit is in review, held or failed. A unit the store has as
  `running` is refused even when no process holds its branch (a pause for the usage window,
  in a rework or not): its composer is disabled with the reason, and `claim` answers 409.
  Taking a new lease also clears the checkpoint's `running_node`, so the files a killed
  node left are the chat's from then on and a later run of that node does not take them as
  its own.
- A turn is policed by who runs it, decided by the session the unit's record names, not by
  the directory it runs in. The unit's own session, resumed, carries the pipeline's policy
  (worktree only, never the specs) plus `no_commit` beside `no_push`; any other session,
  started here or in an editor, carries `ToolPolicy(scoped=False, no_commit=True)`: none of
  the pipeline's rules, but `git commit` and `git push` refused, since the server started it.
  Under Claude the hook runs with `--no-commit`, and `--refusals-only` for the second kind;
  the ACP broker applies the same two.
- A free session may change the unit's worktree and the planning checkout together; after
  its turn the lease covers `worktree` and `planning` when the latter holds changes, and
  counts both. Commit is per checkout. The worktree's commit is adopted as above. The
  planning checkout's (`checkouts: ["planning"]`) goes through `build_commit` with a gate,
  `abk check` and `abk tags` of the unit's change: what they reject is given to the agent,
  which fixes it, and the commit is tried again the helper's bounded number of times, a
  rejection after that answering 409 with the gate's output and keeping the changes. It is
  delivered to no unit; the answer's `consequences` list (`pipeline/consequences.py`) names
  a `Needs:`-only edit (applied by the next tick), a plan change (re-planned by the next
  tick, built units keeping their state) and a changed requirement (started units flagged for
  a rework or a requeue), and changes none of them.
- A commit carries the session in an `Adopted-From` trailer. The unit's check-fix, review and
  rework prompts get a part listing the commits on the branch whose trailer names a session
  other than the build session recorded in the unit's thread (hash, subject, files, session)
  as authoritative and not to be reverted, and, for a test file such a commit changed, asking
  for keep, adapt or retire only if the agent changes it (`pipeline/outside_commits.py`).
  Nothing is stored: the trailer is compared with the recorded session when the prompt is built.
- What the tick does with a dirty worktree depends on the lease and on the thread's
  `running_node`:

  | lease | `running_node` | the tick |
  |---|---|---|
  | held by a live process | any | leaves the unit alone; `abk status` lists it as attached with the number of files |
  | stale, marked as holding changes | any | commits and continues nothing; holds the unit with the cause `attached` |
  | none | names the node being re-run | failure leftovers: resumes over them, the node's commit includes them |
  | none | none | holds the unit as an unexplained dirty tree (`dirty_worktree`) |

  A path named in the repository's `environment.inputs.lock` is never part of a dirty tree:
  it does not hold a unit, is not discarded and is not listed as a leftover.

- `abk attach release <unit>` ends an attachment without the server: `--commit MESSAGE`
  commits every change and releases, `--discard` restores the tree to the branch head
  (tracked files reset, new files removed) and releases, and a dirty tree given neither is
  refused. Both refuse while a step holds the unit's branch, and a commit a hook rejects
  prints the hook's output and keeps the changes and the lease. A unit the tick held as
  `attached` stays held afterwards; `abk requeue` returns it. The page does the same with
  `GET .../changes` (the files at stake), `POST .../discard` (confirmed, refused while a step
  runs or with nothing attached, and accepted for a lease the restarted server holds) and
  the refused release above.
- Commit adopts the chat's changes into the normal cycle, in one request
  (`POST .../commit`, or `abk attach release --commit`): the commit goes through the commit
  helper, which retries a hook that reformats files and then gives a rejecting hook's output
  to the attached session to fix, up to `COMMIT_FIX_ROUNDS`; still rejected, it answers 409
  with the output and keeps the changes and the lease. A made commit carries the `Unit` and
  `Adopted-From` trailers and is written into the lease as `committed` before the `adopted`
  event is delivered, then the lease is removed; the answer is the commit, the unit's state
  and whether the delivery completed. A commit made and not delivered is finished once by
  the next server start, the next `abk attach release` and the tick, and repeating the
  request with the same commit delivers nothing again. `adopted` enters at the checks from
  a unit in review, held or failed (cause `adopted`), clears the recorded node start, never
  reuses the previous approval and gives the checks a fix budget of their own. The review
  after it is round zero: it takes no place in the round limit, cannot hold the unit as
  having spent its rounds, keeps the earlier findings, and if it asks for changes the
  rework is round one. A commit of the planning checkout (`checkouts: ["planning"]`)
  releases that part of the lease and delivers nothing.
- A page is a tab for as long as it is shown. The agent tab holds its tab open with its own
  event stream; the sessions page, which is not any one unit's, holds `/api/tabs/events`
  open for the whole page, whichever session or new-session form it is on. Either stream
  closing is the page closing.
- One turn at a time runs on a session; a second is refused with 409. A session is read-only
  here while another process has it open (`serve/sessions.py`, a scan of `/proc`): one with
  the session id among its arguments, or a `claude` working in the directory the session is the
  newest of, which is how an editor's plain `claude` keeps its session. Continuing such a
  session forks it (Claude's `--fork-session`; for ACP, a new session seeded with the
  history); the first is never written to. An ACP agent that does not advertise both `session/resume` and `session/list`
  cannot resume, so its session is shown from the recorded history and continued as a new
  seeded session. A Claude session whose directory is a unit's worktree goes under the unit's
  lease and is refused while a step runs; it carries the pipeline's tool policy only when it
  is the session the unit recorded.
- A turn on a unit's session runs on the model that session recorded.
- A turn on the unit's own session is prefixed with its change (`serve/spec_context.py`): the
  proposal, design, spec deltas and the unit's task groups, read-only, with the rule that
  tests and code change together. A request that contradicts a requirement is answered first
  with a flag, a fenced `spec-conflict` block of JSON (`requirement`, `reason`), and no edit;
  the bridge turns the block, however the runtime chunks its words, into a `spec_conflict`
  custom event the page shows as a callout. Change the spec instead opens a free session on
  the planning root (`POST /api/sessions` with `repo: "planning"`) with the flag as its first
  message. Other sessions get none of this. The rework prompt carries the same rule for
  review comments: a conflicting one is answered in its thread with the flag and left until
  the reviewer confirms.
- A permission request is offered to the browser (`AgentRequest.on_permission`) only after
  abk's own command rules allowed the call, and only as allow once or a refusal: an "always"
  would make the agent stop asking, and abk's rules would no longer see its calls. The tab
  closing, or no answer, denies it.
- A turn's attachments (file, line range, hunk, selected text) are appended to its prompt.

The browser's client (`web/src/agui.ts`) reads these streams itself. The spike (task 8.8)
found that `@ag-ui/client`'s `HttpAgent` posts one `RunAgentInput` to one url and reads one
run back, while this server has a persistent per-tab stream, its own turn body and a lease to
release, so it would need a `requestInit` override plus a second client, and rxjs and zod in
the bundle; no Node runtime is needed or used. Because every event is valid AG-UI,
adopting the package later is a change to that one file.

### The review tab

The review tab is a tab of the unit page at `/units/<change>/<n>/review`
(`web/src/review/tab.tsx`). It shows the diff the server pinned to one commit
(`GET .../diff`, whose `commit` the tab keeps), a tree of the files, the threads beside
their lines (outdated ones marked), and the latest review round's findings and deferred
follow-ups, all read from `GET .../review`. Selecting a line or range highlights it and
creates nothing; the **Comment** action on a selection opens a composer that posts the
thread (`POST .../review/threads`, with the diff's commit), and each thread offers a reply
box and a resolve toggle (`POST .../replies`, `PATCH .../threads/<id>`). The summary and the
**Request changes** and **Approve** buttons record the round's decision
(`PUT .../review/decision`); a round that already has one answers 409 and the tab shows the
server's reason.

The selection lives in the address, so a line can be linked to:
`?file=<path>&lines=<n>` or `lines=<start>-<end>`, `side=old` for a line of the removed
file (`new` otherwise), and `commit=<sha>` for a line as it was at an earlier commit. With
`commit`, the tab asks `GET .../review/locate?file&line&side&commit` for where the line is
at the branch tip and opens there, or says the line is no longer in the diff. Opening an
address scrolls to it; an address the tab wrote itself is not opened again.

`web/src/review/viewer.tsx` is the only module that knows the diff library
(`@pierre/diffs`, used to parse the patch). Its contract is the DOM: a file is a region
named by its path, a line carries `data-path` and `data-old-line` / `data-new-line`, a
selected line `data-selected`, and a thread is an article that follows the line it ends on.
Hovering a thread highlights its lines with the same `data-selected`, without selecting
them or touching the address. A thread the server could not place at a line (marked
outdated), or whose line the diff does not show, is drawn at the top of its file's region,
collapsed or not; one on a file the patch no longer holds is listed in a separate region of
threads on files no longer in the diff, so no thread is ever left out.

Changes a chat left uncommitted in the unit's worktree come from `GET .../review/working`
(`commit`, `files`, `patch`; untracked files appear as additions). The tab draws them in a
separate "Uncommitted changes" section, marked as not yet committed. Their lines take a
highlight, but **Comment** is disabled with the reason, and the server refuses a thread
posted with `uncommitted: true` (409), since a thread anchors to a commit. **Ask the agent**
on any selection opens the unit's agent tab with one chip holding the file, lines, hunk and
text (`uncommitted: true` for working changes); sending puts them in the turn's prompt, with
uncommitted lines marked as such.

## How a process test fakes the host

A test that runs `abk` as a process fakes GitHub at the host's API, not at the
`gh` command. `tests/forges/github_server.py` is a fake host (`FakeGitHub`) that
answers the forge's routes over HTTP from the recorded answers, numbering its
first pull request as the test asks; the test writes reviews, comments and
merges into it and reads back the requests it received (`requests`,
`unrouted`). `tests/forges/process_host.py` (`process_env`) points the process
at it with `ABK_GITHUB_API_URL` and puts one script on `PATH`: `gh auth token`,
which prints the server's token. Any other `gh` call fails, so a forge that
falls back to the command shows up as a failure.

A review the test writes may carry an inline comment with its own id, path and
line, listed at the pull request's comments. A reply is accepted only to an
inline comment's id (any other id, a review's included, is a 404, as on GitHub)
and creates the empty review GitHub makes for it. Each process-test module
checks `unrouted()` at teardown, so a route the fake does not serve fails the
module naming it, whichever test made the call.

The routes are defined once, in `tests/forges/github_routes.py`: a table of method,
path pattern and handler over one `GitHubState` (pull requests, reviews, inline
comments, labels, statuses, stacks, a run's jobs and logs, and the counters that give
ids), covering the GraphQL listing and draft mutations, stacks, branch protection and
the check and job routes as well as the pull, review, comment, status and label routes.
A guard test fails if a route is registered or answered in either host instead of in
the table. The in-process host
(`GitHubHost`) and `FakeGitHub` both look a request up in a route the test
scripted first and then in that table; a miss is a 404 recorded as unrouted. The
pull request node a listing returns is derived from the state when read, so a
review written through the server is what the in-process host sees.

## Why it is shaped this way

- **Worktrees live outside the planning repo.** Agents reach the specs through
  `--add-dir`; with worktrees inside the planning repo one unit's agent reached
  a sibling unit's worktree through that flag and committed there under an
  invented id, and a type checker resolved a code repo's imports against the
  planning repo's own source. `Installation` refuses a worktree root inside
  the planning root.
- **One workspace member at a time.** Every member tends to own a top-level
  `src` package, so one shared environment makes one member's tests import
  another's. Unit-test and e2e-test run each member with `uv run --package
  <member> --isolated`, the way such a repo's CI does.
- **Archive waits for verify.** A pipeline that stops at merge leaves deploys
  to whoever remembers them; a change was once archived while its consumer
  could not see a single tool it added.
- **The poller acts only on change.** Re-dispatching what it saw last time
  would rework the same unit every five minutes — burning the window,
  force-pushing over itself, drowning the PR in comments. The one exception
  is a change deferred because its unit was being built, which is reported
  again until a handler has acted on it.
- **Units are tracked in a file, not the host's issues.** One committed file beside
  the specs, easy to reset, no debris in the code repos when a change is
  re-planned or abandoned. The cost is that nothing closes a unit on merge, so
  the runner and the poller record state themselves.
- **Tests are committed first.** A test committed with the code it covers has
  never been seen to fail. The separate commit, run red at that commit, is the
  evidence; the policy hook denies `--amend` to keep it.
- **Every push names the SHA it leases against**, because a bare lease is not
  a lease after a fetch.
- **E2e-test is a queue, branch locks fail fast.** A second unit's live tests
  are valid and merely have to wait; a second run on one branch is a bug.
- **A rework is reviewed by a different model** (the runtime's `rework_review` model): a
  small targeted edit, and the model that made it is the worst judge of
  whether it landed. This holds by default because the author is `sonnet`
  and both reviews are `opus`.
- **Nothing here names an installation.** Repos, owners, deploy commands and
  credentials come from `abk.yaml`; the framework is installable anywhere and
  publishable.
