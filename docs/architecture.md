# Architecture

How a change becomes merged, deployed and archived code, and what stops the
unattended parts from doing harm. The examples use a workspace of two repos,
`app` and `platform`, where `app` consumes `platform`.

## The flow

```
change (tasks.md) ─► plan ─► units ─► build ─► PR ─► human review ─► merge
                                                         ▲            │
                                     poll: rework/restack┘            ▼
                                                     verify ─► archive
```

Everything below is a tick (`abk tick`), which a timer runs every few minutes
in the planning repo. One tick starts with a round, in order: check the usage
window, fetch and poll each repo's host, plan what is new, reclaim what no run
holds, verify and archive what has fully merged, and work out what is ready;
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
tests node and before every tier 1 it hashes the inputs there, runs `sync` when the hash
differs from the one recorded in the worktree's git directory, then `check`. A failure with
inputs equal to the base branch's (at the point the branch left it) fails the unit with the
cause `environment`; a failing `sync` or `check` after the unit changed the inputs is an
ordinary tier 1 failure carrying that output.

The lock files named in the repository's `environment.inputs.lock` belong to the pipeline in
its worktrees, because a package manager's `sync` creates or rewrites them. The commit step
(`build_commit`) commits a tracked lock with the unit's change when the unit changed a
dependency input against its current base (the point its branch left it), and otherwise
restores it to the branch's version; a lock the branch does not track is never committed and
stays in the worktree. A restack restores an unchanged tracked lock before it moves the
branch, since a rebase refuses a tree with an unstaged change. The same rules apply to a
commit adopted from a chat.

### 1. An OpenSpec change

A change lives in `openspec/changes/<change>/` in the planning repo:
`proposal.md`, `design.md`, delta specs, and `tasks.md`. The pipeline reads
only `tasks.md`, so two facts have to be on every task-group heading — the
repo the code lands in, and the test tier it needs:

```
## 1. [platform] [tier1] [contract] Accept the new field, keep the old one
## 2. [app] [tier1] Send the new field
## 3. [app] [tier2] [acceptance] Drive the route end to end as a client
## 4. [platform] [tier1] [narrow] Drop the old field
```

`abk tags` (`pipeline/work_graph.py`) checks the contract; the planner
refuses a change with tag errors before spending a model call on it:

- groups are numbered from 1 in build order, every group has at least one
  `- [ ] n.m` task, and `[repo]` is one of `abk.yaml`'s `repos` keys exactly;
- `[tier1]` runs in CI with no external services; `[tier2]` needs the real
  stack on the developer host and is serialized behind one lock;
- an optional third tag is a **flag**. `[contract]` marks a group that widens
  a shape the *other* repo consumes (a wire model field, an event, a tool
  surface). Two repos are never at the same commit, so callers of both shapes
  exist for a window; the widening lands alone and a `[narrow]` group — which
  must be last — removes the old half. Contracts inside one repo need no flag.
  `[acceptance]` marks the group that drives what the change built the way its
  consumer does, on the stack; it is always `tier2`, comes after every group it
  exercises (only `[narrow]` may follow), and gets a unit of its own. Every
  change has one or opts out with a line `Acceptance: none — <reason>`; the
  reason is what review agrees to, and the line without one is an error;
- a `Needs: <other-change> group <n> — why` line inside a group makes it wait
  for a group of another change. The planner orders groups within a change;
  across changes it only sees what is in flight, so a dependency that must
  hold is written down and applied as code (`link_needs`, every tick).
  `Needs: <other-change> group <n> merged — why` also makes the dependent
  wait for the merge (or for a satisfied dependency's work to land) even in the
  same repo, then start on the trunk rather than stacked; use it when the
  dependency is still reshaping what this group builds on. `abk tags` rejects
  it on the change's own group. `link_needs` records it as `merge_before`,
  recomputed from `tasks.md` every tick;

### 2. Planning into units

A **unit** is one PR's worth of task groups, in exactly one repo. It has one
identity, its first change's id and branch, and may also carry groups of other
changes (`Unit.joined`); `Unit.members()` is the single way to ask which
change's groups it builds, its own first. Building, review, ticking, archive
readiness, `Needs:` resolution, the pull request body and the graph all read
members. Once per
change — and again only when the change's specification changes (its
`tasks.md` with checkboxes and `Needs:` lines stripped, hashed into
`runs/planned.json`) — the planner (`pipeline/planner.py`) sends the change,
the units already in flight and `abk.yaml`'s `relationships`/`consumes` prose
to a model and gets the whole graph back as JSON: id (`<change>/<n>`), repo,
tier, `depends_on`, `estimated_lines`, `groups`.

A model is used because the parts that matter are judgements — which groups
touch the same files, what depends on what across changes, how many small
groups make one PR (`limits.min_unit_lines`). Its output schedules real work,
so validation **refuses rather than repairs**: every group claimed exactly once
by a unit in its own repo, no group already built by a merged unit, no unknown
dependency, no cycle, the acceptance group alone in its unit and downstream of
everything it exercises. A bad plan costs one round; `limits.max_plan_attempts`
bounds the retries per version of the file.

Unit size is bounded from both sides. Groups are combined until the estimate
reaches `limits.min_unit_lines`, and never past `limits.max_unit_lines`: the
planner's prompt states the ceiling, and a plan with a unit estimated over it
is rejected and re-asked.
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
repo and tier; a straight line (the later depends on the earlier, nothing else
does, the later waits on nothing else unfinished); both unstarted; no
`[acceptance]`, `[contract]` or `[narrow]` group; no group marked `Separate:` or
`Independent:` (an `Independent: <reason>` group depends on no earlier unit of its
change, and is never joined into a neighbour's unit); the estimates together at
or under `limits.max_unit_lines`. Joins are checked in order against a copy of
the store, so three units in a line can become one in a round. On the write each join is applied under both units' branch locks with
"unstarted" read again; a unit that has started since drops that join alone, the
rest of the plan is written, and the change is planned again next round. A group
another unit carries counts as built when its change is planned again. Each join
is logged with its groups, the unit and the combined estimate.

`UnitStore.upsert` merges the plan into `runs/units.json` by id: shape from
the plan, state/branch/PR/feedback from what is already recorded. A unit the
plan dropped becomes `unplanned` only if it never started.

`abk replan` is the on-demand way to plan: it plans the changes it is given
whatever the recorded hash says, then links the `Needs:` lines, and prints what
changed. Linking only adds dependencies, so removing a stale one is the replan's
work: the plan rebuilds each planned unit's dependencies. `runs/planned.json` is
read, changed and written under a lock, and replaced atomically, so a command beside
a running pass loses no update.

### 3. Building a unit

Each unit has a priority, 1 (most urgent) to 5, 3 by default, set by the planner
in code from the `Priority:` lines of the groups it builds: the most urgent of
them, carried groups included. A started unit keeps the priority it started
with, and the store leaves the default out of a unit's record. `waiting_on_me`
(`pipeline/units.py`) answers which units wait on a unit, across repos and
through chains, and `effective_priority` takes the most urgent of a unit and
those waiting on it.

`ready_units` picks planned units whose dependencies allow: a same-repo
dependency may be `in_review` (the unit stacks on its branch), a cross-repo one
must be `merged` (stacks cannot span repos). A `satisfied` dependency is
looked through to what it was built on: same-repo, the dependent waits on and
stacks on that predecessor; cross-repo, it counts once that predecessor has
merged. `limits.stack_depth_build_cap` holds
back chains of open PRs; `limits.max_concurrent_stacks` bounds units being
built. `limits.max_units_in_progress` bounds the units started and not finished
across repos: running, in review or failed, and any planned or unplanned unit
that a run has started: one with a recorded branch, a pushed or approved commit or a pull request. Merged, closed and satisfied
units, held units (set aside until a person releases them), and units that
never started, do not count. Only a unit that
has never started is stopped by it, and no more of them start than leave room;
a rework, resume, restack, review round or push still runs, so the count can
pass it. Free slots go to
units with an open pull request, then to those resuming a build, then to new
ones, each in planned order. Ready units build in parallel threads, each
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
planning, reclaim, verification and archive, then readiness. A change added or
edited during a pass is planned by its next refresh (a change whose tasks are
unchanged costs no model call), a unit sent back is let in again, and a step
that raises is logged while the others still run. Only the model's own
refusal (a `rate_limit` pause, or a build returning False) ends submission,
and the builds in flight are still awaited. A usage refusal pauses only that
unit: a refused round still fetches, polls and archives, starts nothing, and
later rounds ask the guard again and resume it. A pass therefore
lasts as long as the work it can reach — watch the pass, not a unit.

A round reclaims too: a unit marked `running` that no process holds and that
has no thread to resume goes back to `planned`, so its state is true for as
long as a pause lasts. A unit in flight is left even before its
worker takes the branch lock, and a unit the pass already started is left until
the pass ends. A running unit
that no process holds takes no build slot until the round starts it again, and
is started before planned units. A change that
fully merges early in a long pass is verified live and archived by the next
round, not the next pass; verification takes the live-stack lock without
waiting, and is skipped and logged for that round while a tier 2 run holds it.

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
sequence; `wiring.py` binds each step to git, gh and `claude`:

1. **Usage guard first**, before the worktree exists, so a refusal never
   leaves a half-built unit.
2. **Worktree.** `spec/<change>/<n>` (the prefix is `git.branch_prefix`)
   is checked out under the worktree root, created on its base — the newest
   `in_review` same-repo dependency's branch, else `origin/main`. A dirty
   worktree is refused, never cleaned. A resuming unit whose base moved is
   restacked first; a conflict the resolver cannot settle goes to the
   **adapt** step, which resets the branch, keeps the old work under a ref,
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
   the plan intended.
4. **Implementation, commit.** A second run makes those tests pass and may
   not weaken them; commit `feat: <title>`. A branch left
   with no commits of its own — neither step added one — is not failed
   outright; see the satisfied outcome after tier 1, below.
5. **Checks, then review rounds.** Before each review round the branch has to
   pass tier 1 (lint, formatting, types and the tests; see step 6): a reviewer's
   time goes on a branch that already builds. A failure is saved as feedback and
   handed to the builder with the check prompt, then tier 1 runs again, up to
   `limits.max_check_rounds` times (3; `null` is no limit; 0 means no fix
   attempt, not no check), before the unit is `failed` with the output kept. A
   fix that changes nothing ends it too, whatever the limit. It runs again
   before every later review round with the budget started over, since a
   rework can break the build as easily as the first draft. Nothing runs tier 1 after the review: a reviewer reports and the
   builder fixes, so approval leaves the branch as the checks judged it.
   A read-only reviewer (`Read Grep Glob`, `git diff/log/
   show`, and the forge's read commands, `gh pr view`/`diff` or `az repos pr
   show`; nothing that writes) judges the branch against the repo's `CLAUDE.md` and the change,
   told which round this is, how many remain and what running out costs, and
   answers JSON: `approved`, `feedback`, `findings`, `earlier`, `needs_human`,
   `follow_ups`, `escalate`, `reasoning`. Its prompt names its angles — the
   enclosing function of each hunk, what each removed line enforced, callers
   and callees — and an evidence bar: each candidate is re-checked before it is
   reported. Each finding carries a file, an optional line, a summary, a
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
   the next round is judged by `models.rework_review` and shown the earlier
   rounds. A reviewer that finds another instance of a kind it cannot
   enumerate, or that still disagrees after the builder declined a point once,
   sets `escalate` (`class` or `disagreement`) with its `reasoning`, and the
   unit is `held` for a person instead of spending another round. Up to
   `limits.max_review_rounds`; when the budget is spent with blocking work
   still outstanding, the branch is pushed, its PR carries the open points, and
   the unit is `held` rather than failed. A rework may mark a point `BLOCKED:`
   when its environment refuses the edit (a protected file, a permission); if
   every remaining required change is blocked, the reviewer sets `needs_human`
   and the unit is `held` for a person. Approval records the commit SHA.
6. **Tier 1.** Lint scoped to the unit's diff, then the tests of the members
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
   base, before the push. A move with conflicts goes through the adapt step,
   which accounts for its own tests, and back through the checks and a review. A unit that reaches here with no commits of its own — its groups
   were already implemented, by a predecessor that worked ahead — is judged on
   this check alone: tier 1 passing makes it `satisfied` rather than `failed`,
   its groups ticked and its dependents released, with no PR opened; tier 1
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
7. **Tier 2**, for `tier2` units. If the repo has `dev_stack`, the unit's
   branch is brought up on it (`script up`, `script test`, `script down`,
   always torn down) — and first, when the repo `consumes` one with a dev
   stack of its own, that repo's stack from a detached worktree at its
   `origin/<default_branch>` (the local trunk for a repo with no `origin`), never the user's own checkout. Without a dev
   stack the profile's tier-2 commands run against the live stack. Either way
   under the one `runs/tier2.lock` queue, and the result is recorded with the
   commit, the command, counts and the stack-versions command's output
   (`verify.stack_versions_command`, else the repo's `infra:` profile's; see
   [toolchain-profiles.md](toolchain-profiles.md)) for the PR body. Tier 2 runs in each declared project (`projects:`), from its
   directory and under its profile, as tier 1 does, and from the root when none
   is declared; it runs each member's directory with no
   collection path, so it collects what the member's own pytest
   configuration (`testpaths`) selects. A stack-versions command that cannot
   start is logged and records nothing.
   A run that starts with commits on its branch fetches its repo first (a
   failed fetch is logged, not fatal), then restacks.
8. **Check the base, address new comments, then push.** Just before the push the repo is fetched
   again and the base is worked out afresh: a parent whose pull request the
   forge reports merged, which the store has not heard of, is recorded through
   the merge handler and the unit takes its new base (a forge that cannot be
   asked is logged, and the run goes on with the base it has). The branch is
   moved onto it with the restack a run starts with, but without the conflict
   resolver: a conflict is aborted and the branch left as it was. A clean move
   re-runs tier 1 (and tier 2, for a tier 2 unit) and carries the approval to
   the moved commit; a conflict, or a tier 1 or tier 2 failure on the new base,
   pushes nothing and resumes the unit at its restack in the same run (a
   check's failure leaves its output as feedback). That restack is what
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
   body says when the branch no longer sits on its base. A body over the host's
   description limit shrinks in order: the start of the tier 2 output (its tail
   kept), then the follow-ups to whole items with a line counting the rest, then
   the output altogether, keeping the headings and the pass or fail line; the
   forge cuts whatever is still over. The `local/tier2` commit
   status is posted for the tested SHA (and, on a host that shows statuses on
   the pull request, on the open pull request for the branch too); the rework's replies to review threads
   are posted in those threads, signed with the commit. A reply the host does not take stays in the
   unit's pending replies and is posted on a later pass, once (a reply the host already holds counts as posted). A satisfied
   unit's pull request that cannot be closed is recorded as `close_pending` and closed by each
   round until done, its reason posted once; `abk status` lists both. The unit is
   `in_review`, and its groups are ticked in `tasks.md` — now, not when a
   build finished.

Between steps the unit can be stopped: a same-repo parent went back for
rework (the unit `planned`, with cause `upstream_went_back`), or the usage window filled.
After each fetch and poll, a unit in review is likewise set back to `planned` with that cause
while a same-repo predecessor's branch is changing (a commit beyond its pushed head, rebasing, or
itself planned for a changing upstream or a moved base). It keeps its approval, branch and pull
request, and restacks onto the predecessor's new head when it is released.
Every change that stops a unit, holds it or sends it back (and a merge, a close, a
release, a failure) records a `cause`, a fixed set of values, on its history entry; the
note beside it is prose for people and no code reads it. The entries for starting a run,
reaching review and being satisfied carry none. A pass lets a unit it already
built back in only when its last cause is `rework` or `base_changed` (resuming restacks
it, so what held it is gone), or `host_unavailable` once its backoff has elapsed (the
code host could not be reached; 1, 2, 5, 10, then 30 minutes by consecutive parking); a
unit put back for any other cause waits for the next pass, and the tick log says which cause. A unit held for depth keeps the branch it is
still on as `held_base`, and who holds it as `held_by`. A record with no cause, or one
this release does not know, is never readmitted by the pass; `abk status` lists it.
A usage pause leaves the unit `running`, with its thread interrupted before
the agent node; the first tick the usage guard allows resumes it from there.
A run that is killed is resumed the same way, at the node it was in: nothing
requeues it and nothing commits what it left.

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
tier 1 always runs the suite itself, so one agent's output never reaches another
agent or stands in for tier 1's run.

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
do, since git's own locks there fail rather than wait. A restack's rebase runs
in the repo's own checkout and holds the turn to the end, conflict resolver
included, so a conflicted restack keeps that repo's builds waiting at worktree
add or push until its resolver finishes. Its tier 1 run happens outside the turn.

| Change seen | Event | Effect (`events.py`) |
|---|---|---|
| `mergedAt` set | `merged` | unit `merged`; children in the same repo restacked onto their next open parent (or `main`) — a child being built only has its PR retargeted, and its build holds at the next step and restacks itself when it resumes; a merge only cascades within `limits.stack_depth_rebase_cap`: a child deeper than it is `held` with its depth and the cap on its record and the merged branch is kept, and a later merge in the same repo restacks it once its depth falls within the cap (the branch kept for it is left behind afterwards, like any other leftover local branch); a child being built is not held: it is retargeted as above; the merged unit's worktree removed (refused if dirty) and its local branch force-deleted — GitHub squash-merges, so `-d` would refuse — unless a same-repo dependent holds its lock, when the branch is kept. Deferred while the merged unit itself is being built. |
| closed without merging | `closed` | unit `closed`; nothing cascades to what was stacked on it. Deferred while the unit is being built. |
| label `agent-hold` added | `hold` | unit `held` (`held_by` `reviewer`), taking over a hold for depth, which a merge would otherwise free, and keeping that hold's note so it can be found again; a hold the review loop or the toolchain made keeps its cause. Nothing automatic touches it again, and the label stays until a person removes it. Deferred while the unit is being built. |
| label `agent-hold` removed | `release` | a unit the label held returns to `in_review` and its thread resumes with a release; a depth hold the label took over goes back to being one (`held_by` `depth`, with the `held_base` it kept) while its depth is beyond `limits.stack_depth_rebase_cap`, or, when a merge during the label brought it within, is restacked from the branch it was still on (a thread is resumed at `prepare`); a hold the review loop, a depth cap or the toolchain made (`held_by`; a record without one is not read from its note) stays held and the log says so. A comment or failing check that arrived during the hold is not recorded as seen with the release, so the next poll delivers it. Deferred while the unit is being built. |
| a check the host cancelled (GitHub `CANCELLED`; on Azure DevOps a build policy whose build ended `canceled`) that was not cancelled at the last poll, or one first seen already cancelled | `rerun_checks` | the forge is asked to run the cancelled checks again, with no agent: a cancelled check says nothing about the commit, so it is not a failing check and raises no rework. The count is on the stored unit against its last pushed commit and starts again when the head moves; past `limits.max_check_reruns` (default 2) nothing is asked for and the log says the host keeps cancelling the checks. A re-run check that then fails is reworked as any failing check is; a poll that finds both cancelled and failing checks dispatches both events. |
| label `agent-rework` added, `reviewDecision` becomes `CHANGES_REQUESTED`, a new comment or submitted review id, a newly failing check, or a pull request that becomes unmergeable (on Azure DevOps, `mergeStatus: conflicts`; an undetermined answer, which the host gives for a while after every push and whenever the base moves, is not a conflict and dispatches nothing; the snapshot keeps the last definite answer through it, so the conflict it resolves back into is not new). A PR first seen already red or already unmergeable is dispatched too. | `rework`, carrying the kind that sent the unit back (`failing_checks`, `conflict`, `label`, `changes_requested`, `comment`) | what the unit is handed is chosen by that kind and never by the reason's text, and the feedback is saved with its source (`review`, `ci`, `conflict`, `tier1`, `tier2`), which picks the fix-the-checks prompt. The reviewer's words (review bodies, inline comments still attached to a line, the latest comment) become the unit's feedback and it returns to `planned`; for failing checks the feedback is the failed jobs' logs (from the run's jobs, the tail up to the last error); for a conflict it is the conflict alone, and the restack at the start of the run does the rebase. A held unit does not take it: the comment stays new, is delivered as a rework once the unit is released, and the wait is logged once. A comment on a satisfied unit, or on a pull request with no unit, is consumed. Deferred while the unit is being built. A rework asked for by the `agent-rework` label also takes that label off once acted on, so it can be given again; a label that will not come off is left and acted on once. |

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
itself, and the last two have no pull request of their own to carry one.
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
a moved base) or `reworking` (it is answering review or check feedback), else
`running`. These are derived from the unit's record, never stored, and `abk
status`, the graph and the state label show them.

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
Claude run that is told both sides' intent (both are planned units), which
paths arrived with a replayed resolution, and may edit only the conflict.
Leaving a replayed file unchanged accepts it, editing it replaces what's
cached for the next replay, and planting a `<<<<<<<` in it rejects the
replay — which aborts the move and forgets that cached entry so the next
sibling sees the conflict fresh. The result is checked — no markers left, the
moving unit's own tokens still present — or the rebase is aborted and left
for a person. After a clean move
whose diff (`git patch-id`) is unchanged and whose head review had approved,
tier 1 runs again and the branch is pushed with a lease and a "Restacked"
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
tier-2 lock, since both use the one live stack:

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
  changed paths, selected by `tests.tier2_marker` and excluding
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
marker: each returns the text unchanged when it fits, never returns more than the size,
and closes any code fence or `<details>` block it leaves open. `forges.base.fit_description`
is a wrapper over `cut_head` with the description note as its marker.

`fit` shares a budget between `Section`s (a render function, a natural size, a smallest
honest form, a weight, an optional ceiling and whether it is required). Everything is
rendered in full when it fits; otherwise every section gets its smallest form (dropping
from the lowest weight up, never a required one), the rest is shared by weight, and a
section needing less than its share keeps only what it needs and passes the remainder on.
A render that overshoots is trimmed from the section with the most room and rendered again
(up to three times), and a final line cut guarantees the budget. Ties go to the earlier
section, so the result is deterministic.

## The guards

None of these rely on the prompt being followed. All three read as they do
because Claude Code is the default runtime; the hook contract and the usage
window are its own. The `acp` runtime, when selected, is not held by the usage
window (`cmd_tick` in `cli/pipeline.py` and `wiring.build_may_start` skip it),
and it enforces the command rules through client capabilities and permission
answers instead of the hook. The details are in
[agent-runtimes.md](agent-runtimes.md).

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

**The usage guard** (`usage_guard.py`, `pause.py`). The account is a
subscription with a usage window shared with the user's own sessions, and
credits past the plan limit cost money. No new unit starts once a window is
at its threshold; the reading comes live from the usage endpoint with Claude
Code's stored OAuth token (kept in `usage-cache.json` for a time that adapts, and never past a
window's reset). The time starts at `usage_cache_minutes` (fifteen by default); each refusal doubles it up to
`usage_cache_max_minutes` (an hour by default), a longer retry time a refusal names is respected, and each quiet
stretch of that time halves it, never below the configured value. It is worked out from `usage-calls.jsonl`, and
`abk status` shows the time in use and what set it. A rate-limit answer starts a cool-down kept with that file, a timeout is retried
once, and a failed call uses the last good live reading younger than `usage_fallback_minutes`
(thirty by default, source `cache`), then Claude Code's own cache when it is under an hour old. **An unknown reading pauses.**
**A pause never ends before it is written:** the grace after a reset is added
once, in `pause.py`; a reset time already past is treated as unknown (retry
after thirty minutes); and a reading too old to trust refuses starts for the
stale-retry interval (`usage_stale_retry_minutes`, five by default) without
borrowing its window. A reading served from the cache file has its own source,
so it is not mistaken for a live one.
**Every use of the endpoint is recorded** (`usage_calls.py`) in `usage-calls.jsonl`, beside the
cache in the state directory and gitignored: one line per call or cache answer with the time, the
caller (`guard`, `status` for the runtime's usage status, `cli-status` for the status command, `tracks`), the outcome (`ok`,
`rate_limited`, `timeout`, `error` or `cache`), the status, the latency, the rate-limit and retry
headers of the answer and, for the cache, the reading's age. It holds no token, keeps a week, and
archiving a change leaves it. From it `abk status` prints one line (calls in the hour, refusals,
the cache's share and the shortest interval between successful calls that no refusal followed
within a minute), and the figures are exported as `abk.usage.calls` by outcome and caller and the
gauge `abk.usage.safe_interval` in whole seconds, drawn from the record when the metrics store is
down.
**A step already running is never interrupted** — the guard only ever gates
what starts next, and a step that ends having written nothing is not judged against the window.

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

A pause writes `runs/paused.json` with a deadline, a reason and a kind. The
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
empty run. Results are cached by patch-id so a restack does not re-run them.
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

- **A command limit.** Every command tier 1 runs has a time limit,
  `limits.tier1_command_seconds` (an hour by default), far over what a suite takes. A
  command past it is sent SIGABRT in its process group, so a runtime that can dump the
  stacks of its threads does; one that ignores that is killed after
  `limits.tier1_abort_grace_seconds`. Tier 1 fails with the command, the time
  ("timed out after N seconds") and the end of its output, dump included. This catches a
  run whose tests all pass and whose process then does not exit.
- **A test time limit.** `tests/time_limit.py` fails a test that runs past
  its limit from a timer thread, in setup, call and teardown alike: `--test-time-limit` (sixty
  seconds) for a test without the `local_stack` marker, `--tier2-test-time-limit` (thirty
  minutes) for one with it, zero turning either off. The failure names the limit and its kind;
  the run goes on (see `docs/agent-runtimes.md`, Test markers).
- **A guard.** `tests/timing_hazards.py` parses the test tree and fails on a bare sleep, a
  function that makes a thread and neither joins nor signals it, or a fixed port, except in
  the shared helpers and the files on its allowlist. The allowlist may only shrink: a file
  whose uses are gone fails the guard until it is removed.
- **A wait helper.** `tests/waiting.py` `wait_for(condition, what=, timeout=)` is the one way
  to wait for a condition; it names what it waited for on timeout.
- **A step to call.** The output cap's pass is `scratch.cap_files`, idempotent (a cut file is
  within the limit and is not rewritten), and `scratch.watch_folder` yields an event set after
  each pass, so a test calls the step or waits on the signal and never polls a file.
- **A flake is isolated, recorded and fixed once.** When tier 1 fails on tests, the profile's
  optional `failed_tests` and `serial_rerun_command` hooks give the failed identifiers and a
  serial command for just them, and `build_tier1` runs that twice. A rerun that fails leaves
  the failure as it was. Both passing raises `FlakeFound`: the unit's node calls the runner's
  `on_flake`, which has `flakes.wait_on_fix` make sure, under `flakes.lock` in the state
  directory, that one open change exists for the test (a successor, `-2` and on, only after
  the earlier one is archived) and add a `Needs: <change> group 1 merged` line to each of
  the unit's groups, and appends the flake to `flakes.jsonl`. The unit is held `planned`,
  cause `gated`, with a `resume` requeue waiting, so `release_gated` resumes it once the fix
  has merged: it restacks and runs tier 1 again. A unit of the fix change itself does not
  wait. `abk status` lists each flaky test with its count and fix change.

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
| `abk.agent.cost` | counter (USD) | repo, tier, node, role, model, source (measured, estimated) |
| `abk.node.duration` | histogram (s) | node |
| `abk.wait.duration` | histogram (s) | bucket (slot, usage_pause) |

The last four are the usage ledger's figures, exported by the recorder that writes a ledger
line: an agent record adds its cost and tokens, a span its time. A figure a record lacks adds
nothing, and with telemetry off nothing is exported.

`abk telemetry push-dashboard` pushes the packaged dashboard to the Grafana at `ABK_GRAFANA_URL`.
`ABK_GRAFANA_TOKEN` is optional: set, every call carries it as a bearer token; unset, the calls
carry no authorization header, for a Grafana that accepts anonymous editing. A 401 or 403 on an
anonymous push is reported as a refusal that names the token setting.

Unit ids and change names are on spans only, never on a metric. Tokens are recorded where the
runtime's output carries them: Claude Code's result event, and the `usage` of an `acp` agent's
prompt response when it sends one.

## State on disk

The planning repo's state directory (`planning.state_dir`, default `runs/`):

| File | What | Loss means |
|---|---|---|
| `units.json` | every unit: state, branch, PR, pushed and approved SHAs, feedback, history. In-run progress (review rounds, deferred follow-ups, pending replies) is in the unit's thread, not here; only `approved` and `predecessor_note` stay, because the push gate and the restack write them with no run in progress. A store whose unit still carries a value in `review_rounds`, `deferred`, `pending_replies`, `person_comments`, `resume_from` or `classic_run` is refused when read, naming the unit and the field; the empty `resume_from` and `classic_run` the last release wrote on every unit are dropped on read. A key no field of this release names is dropped on read when empty (a newer release's field carries nothing, and the next write omits it) and refused when it holds a value, naming the unit, the field and the value and saying a newer release wrote it: the value is information this release cannot keep. The truth; the graph page is a view of it. | rebuilt work. Commit it. |
| `verified.json` | the last verification of each change and the units it covered. | a change verified again. |
| `planned.json` | hash and attempt count per change's specification. | one planning model call per change. |
| `prs-<repo>.json` | the poller's snapshot per repo. | the next poll only records; events in the gap are missed. |
| `own-posts.json` | ids of the pipeline's own PR comments and reviews. | a unit reworked over its own reply. |
| `given-comments.json` | ids of a person's comments a rework addressed before its push. | the same comments reported as a second rework after the push. |
| `held-waiting.json` | the held units that have already logged that a comment is waiting on them. | the wait is logged once more. |
| `paused.json` | the current pause, until when and why. | one usage check. |
| `usage-ledger.jsonl` | the usage ledger: one JSON line per agent call (see below). Gitignored. | the spend history, not the work. |
| `usage-cache.json` | the live usage reading (kept `usage_cache_minutes` to `usage_cache_max_minutes`) and any rate-limit cool-down. | one endpoint call. |
| `tier2.lock`, `locks/` | the tier-2 queue lock; branch, repo and store locks. | nothing; kernel-released. |
| `unit-logs/<change>-<nn>-<YYYYMMDD-HHMMSS>-<step>.log` | one file per unit run: a header (unit, change, step, model, base, start), that unit's lines, then the outcome. `<nn>` is the unit's number padded to two digits, so a change's units sort in order and a unit's runs sort by time. The last three runs of a unit are kept; archiving a change removes its files. The file name and `started:` are UTC; each entry starts with the tick's own local-time `[HH:MM:SS]`, the same stamp it prints (the closing `outcome:` line has none: the line above it, the run's last, does). Agent replies and tool-call commands are written whole, line breaks kept; each further line of an entry starts with four spaces (`run_log.CONTINUATION`) and has no stamp, so every line that starts at the margin is a new entry. The journal keeps its one clipped line per step. The unit's `run_log` names its latest. Gitignored. | a unit's transcript; the tick's own output is unchanged. |
| `transcripts/<change>-<nn>-<YYYYMMDD-HHMMSS>-<node>-<round>.jsonl` | one file per agent run of a unit (implement, rework, review, checks fixes) or chat turn, named like a run log plus the node and review round that made the call (round 0 outside a round). One JSON event per line, appended as the agent streams, the same shape for Claude Code and ACP: `kind` (`text`, `reasoning`, `tool_call`, `tool_result`, `plan`, `usage`, `permission`, `stop`), `at`, `unit`, `node`, `round`, `session`, `source` (`build` or `chat`), `text`, `tool`, `call` (a tool call's id, repeated by its result), `input`, `usage` and `truncated`. A tool result longer than `limits.transcript_result_chars` is cut there, ends with `… [cut: the result was N characters long]`, and carries the original length in `truncated`. A text or reasoning event is a whole message or thought, not a streamed fragment, and a user-side event of the Claude stream contributes only tool results. The calls of one run (a unit thread's pass, or one chat turn) share the run's stamp, and the last `limits.transcript_runs_kept` such runs of a unit are kept, whole; archiving a change removes its files. Local only, never committed or sent anywhere. | the agent tab's replay of a unit; the run log is unchanged. |
| `<run id>-<repo>-<track>.md`, `tracked-issues.md` | the tracks' run logs and issue tracker. | history the tracks read. |

The tick commits nothing. The template `.gitignore` excludes only the locks,
`.env`, `.last-runs/` (the tracks' raw output), `unit-logs/` (the unit run
logs) and the usage ledger; `units.json`, the tracks' run logs
and the graph page (`planning.graph_page`, rewritten on every store write) are
meant to be committed by the operator, and the pipeline commits the tracks' run
logs and `tracked-issues.md` by path after each phase, and keeps the planning repo on its
default branch (a stray branch is kept and reported; a rewritten default branch stops the run;
a tick checks the default branch out before reading state). Unit worktrees live under the worktree
root — `~/.local/share/<planning dir>/worktrees` unless configured — and the
planning repo's `.env` holds machine-local settings.

### The usage ledger

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

The `cost` object holds the call's own spend (`incremental_usd`), the session's running total as
the runtime reported it (`cumulative_usd`), `basis` and, where a gateway's figure is recorded
instead, the runtime's own incremental figure (`reported_usd`). `basis` is one of `reported` (the
runtime gave the call's own figure), `derived` (the difference of two cumulative figures),
`first` (the session's first call, baseline 0), `unknown` (a resumed call with no known
baseline: no incremental figure, never the total), `backfilled` or `legacy`. A running total
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
| a tier 1 command | `build_tier1`, one per command, under `command` | empty |

Recording is as best-effort as the agent lines and shares their once-per-process report. The
usage reader skips every line that is not an agent call.

#### Metric records

The same file carries `kind: metric` lines, whether or not telemetry is on
(`pipeline/metric_records.py`). Each is written beside the instrument it mirrors and carries the
instrument's `metric` name, its `value` and its `attributes`, plus the `unit` and `change` it
belongs to where there is one (an exported metric never carries them):

| `metric` | written when | `value` |
|---|---|---|
| `abk.tick.duration` | a tick ends | seconds |
| `abk.unit.duration` | a unit's run ends | seconds |
| `abk.review.rounds` | a unit's run ends other than paused | the review rounds it took |
| `abk.checks.failures` | a tier 1 run fails | 1 |
| `abk.usage.pauses` | a pause for the usage window or a rate limit begins | 1 |

Durations and counts are the very figures given the instruments, so a total derived from the
records equals the exported one. The archive roll-up leaves these lines as they are, and the usage
reader skips them. Recording is best-effort like the rest of the ledger.

An `acp` agent's `thoughtTokens` are not read: only `outputTokens` is recorded, and whether it
includes reasoning tokens depends on the agent. Move the ignore line if `planning.state_dir` is changed.

## The web server

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

## Why it is shaped this way

- **Worktrees live outside the planning repo.** Agents reach the specs through
  `--add-dir`; with worktrees inside the planning repo one unit's agent reached
  a sibling unit's worktree through that flag and committed there under an
  invented id, and a type checker resolved a code repo's imports against the
  planning repo's own source. `Installation` refuses a worktree root inside
  the planning root.
- **One workspace member at a time.** Every member tends to own a top-level
  `src` package, so one shared environment makes one member's tests import
  another's. Tier 1 and tier 2 run each member with `uv run --package
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
- **Tier 2 is a queue, branch locks fail fast.** A second unit's live tests
  are valid and merely have to wait; a second run on one branch is a bug.
- **A rework is reviewed by a different model** (`models.rework_review`): a
  small targeted edit, and the model that made it is the worst judge of
  whether it landed.
- **Nothing here names an installation.** Repos, owners, deploy commands and
  credentials come from `abk.yaml`; the framework is installable anywhere and
  publishable.
