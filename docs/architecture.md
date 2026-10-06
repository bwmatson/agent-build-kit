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
in the planning repo. One tick, in order: check the usage window, fetch and
poll each repo's host, plan what is new, verify and archive what has fully
merged, work
out what is ready, and build it. Every step is idempotent, and a tick with
nothing to do exits silently before reading usage or calling any host.

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
The ceiling shapes plans only. An estimate is not checked against the branch,
so a unit can still land larger than the ceiling.

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

### 3. Building a unit

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
evaluation, and `--only` narrows every one. Planning stays once per pass. A
build reporting that the pass should stop (the usage window spent) ends
submission, and the builds in flight are still awaited. A pass therefore lasts
as long as the work it can reach — watch the pass, not a unit.

A tick reclaims first: a unit marked `running` that no process holds and that
has no thread to resume goes back to `planned` before the usage check, so its
state is true for as long as a pause lasts. Reclaiming, verifying and archiving also stay at the start of a pass. With a
oneshot timer, a change that fully merges early in a long pass is verified
live and archived by the next pass, not the moment it merges.

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
   not weaken them; commit `feat: <title>`. A step that ends having added
   nothing against an exhausted usage window reads as a quiet refusal rather
   than nothing to do, and pauses (see the usage guard, below). A branch left
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
   `origin/<default_branch>`, never the user's own checkout. Without a dev
   stack the profile's tier-2 commands run against the live stack. Either way
   under the one `runs/tier2.lock` queue, and the result is recorded with the
   commit, the command, counts and the stack-versions command's output
   (`verify.stack_versions_command`, else the repo's `infra:` profile's; see
   [toolchain-profiles.md](toolchain-profiles.md)) for the PR body. Tier 2 runs from each member's directory with no
   collection path, so it collects what the member's own pytest
   configuration (`testpaths`) selects. A stack-versions command that cannot
   start is logged and records nothing.
   A run that starts with commits on its branch fetches its repo first (a
   failed fetch is logged, not fatal), then restacks.
8. **Check the base, then push.** Just before the push the repo is fetched
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
   body says when the branch no longer sits on its base. The `local/tier2` commit
   status is posted for the tested SHA (and, on a host that shows statuses on
   the pull request, on the open pull request for the branch too); the rework's replies to review threads
   are posted in those threads, signed with the commit. The unit is
   `in_review`, and its groups are ticked in `tasks.md` — now, not when a
   build finished.

Between steps the unit can be stopped: a same-repo parent went back for
rework (`held before <step>`, the unit `planned`), or the usage window filled.
A usage pause leaves the unit `running`, with its thread interrupted before
the agent node; the first tick the usage guard allows resumes it from there.
A run that is killed is resumed the same way, at the node it was in: nothing
requeues it and nothing commits what it left.

### 4. Polling and events

Which host answers is a forge's business (see
[code-forges.md](code-forges.md)); everything below is written in the typed
values a forge returns, not in any host's JSON. A forge opens a pull request,
posts a status and answers a review comment; it also closes one — the one
call the satisfied outcome above needs, and nothing else does.

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
| label `agent-hold` removed | `release` | a unit the label held returns to `in_review` and its thread resumes with a release; a depth hold the label took over goes back to being one (`held_by` `depth`, its note as the restack wrote it) while its depth is beyond `limits.stack_depth_rebase_cap`, or, when a merge during the label brought it within, is restacked from the branch it was still on (a thread is resumed at `prepare`); a hold the review loop, a depth cap or the toolchain made (`held_by`, or for a record without one a last note of "held by a reviewer") stays held and the log says so. A comment or failing check that arrived during the hold is not recorded as seen with the release, so the next poll delivers it. Deferred while the unit is being built. |
| a check the host cancelled (GitHub `CANCELLED`; on Azure DevOps a build policy whose build ended `canceled`) that was not cancelled at the last poll, or one first seen already cancelled | `rerun_checks` | the forge is asked to run the cancelled checks again, with no agent: a cancelled check says nothing about the commit, so it is not a failing check and raises no rework. The count is on the stored unit against its last pushed commit and starts again when the head moves; past `limits.max_check_reruns` (default 2) nothing is asked for and the log says the host keeps cancelling the checks. A re-run check that then fails is reworked as any failing check is; a poll that finds both cancelled and failing checks dispatches both events. |
| label `agent-rework` added, `reviewDecision` becomes `CHANGES_REQUESTED`, a new comment or submitted review id, a newly failing check, or a pull request that becomes unmergeable (on Azure DevOps, `mergeStatus: conflicts`; an undetermined answer, which the host gives for a while after every push and whenever the base moves, is not a conflict and dispatches nothing; the snapshot keeps the last definite answer through it, so the conflict it resolves back into is not new). A PR first seen already red or already unmergeable is dispatched too. | `rework` | the reviewer's words (review bodies, inline comments still attached to a line, the latest comment) become the unit's feedback and it returns to `planned`; for failing checks the feedback is the failed jobs' logs (`gh run view --log-failed`, the tail); for a conflict it is the conflict alone, and the restack at the start of the run does the rebase. A held unit does not take it: the comment stays new, is delivered as a rework once the unit is released, and the wait is logged once. A comment on a satisfied unit, or on a pull request with no unit, is consumed. Deferred while the unit is being built. A rework asked for by the `agent-rework` label also takes that label off once acted on, so it can be given again; a label that will not come off is left and acted on once. |

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

A pull request is also a **draft** while its unit is `running` and published
when it is `in_review`, written from the same state-change hook; other states
leave it alone, and a refused write is logged without touching the unit.

The pipeline's own posts — restack notes, rework replies — carry a hidden
marker and their ids are recorded in `runs/own-posts.json`, so the poller does
not send a unit back for answering itself, and a rework is never handed its
own summary as review.

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
archives), and never twice. A conflict raises rather than being auto-resolved.

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
Code's stored OAuth token (cached three minutes), falling back to Claude
Code's own cache when it is under an hour old. **An unknown reading pauses.**
**A step already running is never interrupted** — the guard only ever gates
what starts next. The one place that reading is taken mid-unit rather than
only at a boundary is judging a step that ends having written nothing: an
agent told it is out of usage can finish cleanly having said so in prose, and
against an exhausted window that empty result is a pause, not a failure — one
more read of the same guard, never a poll, and the same shape (a `running` unit,
interrupted before its next agent node) as a stop between steps. Empty for any other reason still
fails.

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
**red for an accepted reason** — an assertion, `NotImplementedError`, a
missing module or attribute; not a syntax error, a missing fixture or an
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
| `abk.agent.tokens` | counter | role, model, kind (input, output, cache) |
| `abk.usage.pauses` | counter | kind (usage, rate_limit) |
| `abk.units.reclaimed` | counter | |
| `abk.units` | gauge | state |

Unit ids and change names are on spans only, never on a metric. Tokens are recorded where the
runtime's output carries them (Claude Code's result event); the `acp` runtime reports its one turn
and no tokens.

## State on disk

The planning repo's state directory (`planning.state_dir`, default `runs/`):

| File | What | Loss means |
|---|---|---|
| `units.json` | every unit: state, branch, PR, pushed and approved SHAs, feedback, history. In-run progress (review rounds, deferred follow-ups, pending replies) is in the unit's thread, not here; only `approved` and `predecessor_note` stay, because the push gate and the restack write them with no run in progress. A store the previous engine left may still carry `resume_from` and the in-run keys, which load and are moved onto the thread by the first tick. The truth; the graph page is a view of it. | rebuilt work. Commit it. |
| `verified.json` | the last verification of each change and the units it covered. | a change verified again. |
| `planned.json` | hash and attempt count per change's specification. | one planning model call per change. |
| `prs-<repo>.json` | the poller's snapshot per repo. | the next poll only records; events in the gap are missed. |
| `own-posts.json` | ids of the pipeline's own PR comments and reviews. | a unit reworked over its own reply. |
| `held-waiting.json` | the held units that have already logged that a comment is waiting on them. | the wait is logged once more. |
| `paused.json` | the current pause, until when and why. | one usage check. |
| `usage-cache.json` | the live usage reading, three-minute TTL. | one endpoint call. |
| `tier2.lock`, `locks/` | the tier-2 queue lock; branch, repo and store locks. | nothing; kernel-released. |
| `unit-logs/<change>-<nn>-<YYYYMMDD-HHMMSS>-<step>.log` | one file per unit run: a header (unit, change, step, model, base, start), that unit's lines, then the outcome. `<nn>` is the unit's number padded to two digits, so a change's units sort in order and a unit's runs sort by time. The last three runs of a unit are kept; archiving a change removes its files. The file name and `started:` are UTC; each line carries the tick's own local-time `[HH:MM:SS]`, the same stamp it prints (the closing `outcome:` line has none: the line above it, the run's last, does). The unit's `run_log` names its latest. Gitignored. | a unit's transcript; the tick's own output is unchanged. |
| `<run id>-<repo>-<track>.md`, `tracked-issues.md` | the tracks' run logs and issue tracker. | history the tracks read. |

The tick commits nothing. The template `.gitignore` excludes only the locks,
`.env`, `.last-runs/` (the tracks' raw output) and `unit-logs/` (the unit run
logs); `units.json`, the tracks' run logs
and the graph page (`planning.graph_page`, rewritten on every store write) are
meant to be committed by the operator, and the pipeline commits the tracks' run
logs and `tracked-issues.md` by path after each phase, and keeps the planning repo on its
default branch (a stray branch is kept and reported; a rewritten default branch stops the run;
a tick checks the default branch out before reading state). Unit worktrees live under the worktree
root — `~/.local/share/<planning dir>/worktrees` unless configured — and the
planning repo's `.env` holds machine-local settings.

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
