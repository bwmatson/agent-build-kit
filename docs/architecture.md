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

### 2. Planning into units

A **unit** is one PR's worth of task groups, in exactly one repo. Once per
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

`UnitStore.upsert` merges the plan into `runs/units.json` by id: shape from
the plan, state/branch/PR/feedback from what is already recorded. A unit the
plan dropped becomes `unplanned` only if it never started.

### 3. Building a unit

`ready_units` picks planned units whose dependencies allow: a same-repo
dependency may be `in_review` (the unit stacks on its branch), a cross-repo one
must be `merged` (stacks cannot span repos). `limits.stack_depth_cap` holds
back chains of open PRs; `limits.max_concurrent_stacks` bounds units being
built, not PRs awaiting review. Ready units build in parallel threads, each
under a branch lock (`runs/locks/`) that fails fast: two runs on one branch is
a scheduling bug, not a queue.

A pass keeps scheduling until it runs out of ready work. Each build that
finishes is followed by a fresh fetch and poll and a fresh `ready_units`, so a
parent reaching review starts its child, and a dependency merging releases its
dependent, in the same pass rather than the next; the caps apply to every
evaluation, and `--only` narrows every one. Planning stays once per pass. A
build reporting that the pass should stop (the usage window spent) ends
submission, and the builds in flight are still awaited. A pass therefore lasts
as long as the work it can reach — watch the pass, not a unit.

Reclaiming, verifying and archiving also stay at the start of a pass. With a
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

`UnitRunner.run` (`pipeline/stack_runner.py`) is the sequence; `wiring.py`
binds each step to git, gh and `claude`:

1. **Usage guard first**, before the worktree exists, so a refusal never
   leaves a half-built unit.
2. **Worktree.** `spec/<change>/<n>` (the prefix is `github.branch_prefix`)
   is checked out under the worktree root, created on its base — the newest
   `in_review` same-repo dependency's branch, else `origin/main`. A dirty
   worktree is refused, never cleaned. A resuming unit whose base moved is
   restacked first; a conflict the resolver cannot settle goes to the
   **adapt** step, which resets the branch, keeps the old work under a ref,
   and has the rework model port it while deciding keep/adapt/retire for every
   test the old work had — decisions the pipeline checks and the reviewer
   judges.
3. **Tests, commit.** One scoped `claude -p` writes the group's tests (stubs
   allowed: signatures raising `NotImplementedError`, model fields), runs lint
   and format, and stops. The pipeline commits `test: <title>`.
4. **Implementation, commit.** A second run makes those tests pass and may
   not weaken them; commit `feat: <title>`. No commits means the unit fails —
   unless the usage window is exhausted, which reads as a quiet refusal
   rather than nothing to do, and pauses instead (see the usage guard,
   below).
5. **Review rounds.** A read-only reviewer (`Read Grep Glob`, `git diff/log/
   show`) judges the branch against the repo's `CLAUDE.md` and the change and
   answers JSON: `approved`, `feedback`, `needs_human`. An unreadable reply is
   a rejection. Rejected feedback goes to a rework run, which commits and
   accounts for each point; the next round is judged by `models.rework_review`
   and shown the earlier rounds. Up to `limits.max_review_rounds`; the last
   round's verdict stands. A rework may mark a point `BLOCKED:` when its
   environment refuses the edit (a protected file, a permission); if every
   remaining required change is blocked, the reviewer sets `needs_human` and
   the unit is `held` for a person. Approval records the commit SHA.
6. **Tier 1.** Lint scoped to the unit's diff, then the tests of the members
   it touched (see [toolchain-profiles.md](toolchain-profiles.md)). A failure
   is kept as feedback, so the retry is one scoped rework rather than a
   rebuild.
7. **Tier 2**, for `tier2` units. If the repo has `dev_stack`, the unit's
   branch is brought up on it (`script up`, `script test`, `script down`,
   always torn down) — and first, when the repo `consumes` one with a dev
   stack of its own, that repo's stack from a detached worktree at its
   `origin/<default_branch>`, never the user's own checkout. Without a dev
   stack the profile's tier-2 commands run against the live stack. Either way
   under the one `runs/tier2.lock` queue, and the result is recorded with the
   commit, the command, counts and `verify.stack_versions_command`'s output
   for the PR body.
8. **Push, with a lease.** The head must be the exact commit review
   approved, or the push is refused. The push carries
   `--force-with-lease=<branch>:<sha last pushed>` (the store remembers the
   SHA across processes) or no force at all for a first push. Then the PR is
   created — or edited, on a re-push — with a body saying where it sits in the
   stack, what it assumes, and how it was verified; the `local/tier2` commit
   status is posted for the tested SHA; the rework's replies to review threads
   are posted in those threads, signed with the commit. The unit is
   `in_review`, and its groups are ticked in `tasks.md` — now, not when a
   build finished.

Between steps a **checkpoint** can stop the unit: a same-repo parent went
back for rework (`held before <step>`), or the usage window filled
(`paused before <step>`). The step is recorded in `resume_from`, and the
resume starts exactly there.

### 4. Polling and events

Which host answers is a forge's business (see
[code-forges.md](code-forges.md)); everything below is written in the typed
values a forge returns, not in any host's JSON.

Nothing here is reachable from the internet, so `gh_poller.py` polls
one listing per repo instead of taking webhooks, and only for branches with
the agent prefix. Each poll diffs against a snapshot (`runs/prs-<repo>.json`)
and **acts only on a change**; the first poll of a repo records without
dispatching. Two failed polls back off for thirty minutes.

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
| `mergedAt` set | `merged` | unit `merged`; children in the same repo restacked onto their next open parent (or `main`) — a child being built only has its PR retargeted, and its build holds at the next step and restacks itself when it resumes; the merged unit's worktree removed (refused if dirty) and its local branch force-deleted — GitHub squash-merges, so `-d` would refuse — unless a same-repo dependent holds its lock, when the branch is kept. Deferred while the merged unit itself is being built. |
| closed without merging | `closed` | unit `closed`; nothing cascades to what was stacked on it. Deferred while the unit is being built. |
| label `agent:hold` added | `hold` | unit `held`; nothing automatic touches it again. Deferred while the unit is being built. |
| label `agent:rework` added, `reviewDecision` becomes `CHANGES_REQUESTED`, a new comment or submitted review id, or a newly failing check | `rework` | the reviewer's words (review bodies, inline comments still attached to a line, the latest comment) become the unit's feedback and it returns to `planned`; for failing checks the feedback is the failed jobs' logs (`gh run view --log-failed`, the tail). A held unit ignores it. Deferred while the unit is being built. |

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
paths arrived with a replayed resolution, and may edit only the conflict; the
result is checked — no markers left, the moving unit's own tokens still
present — or the rebase is aborted and left for a person. After a clean move
whose diff (`git patch-id`) is unchanged and whose head review had approved,
tier 1 runs again and the branch is pushed with a lease and a "Restacked"
comment. Anything else — a resolved conflict, a changed diff, a head review
never approved — goes back to `planned` to be reviewed before it is pushed.

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
intentions. It runs only when every unit merged **and** verification passed,
in merge order (two changes touching one requirement conflict when the second
archives), and never twice. A conflict raises rather than being auto-resolved.

## The guards

None of these rely on the prompt being followed. All three read as they do
because Claude Code is the only runtime today; the hook contract and the usage
window are its own, and what generalizing them would mean is
[agent-runtimes.md](agent-runtimes.md).

**The policy hook** (`hooks/policy.py`, `pipeline/command_policy.py`). Every
agent run passes `--settings` registering a `PreToolUse` hook for `Bash`,
`Edit`, `Write`, `MultiEdit` and `NotebookEdit` — per run, never in the user's
global settings. It denies: every registered forge's way of merging — `gh pr
merge`, `az repos pr update`, `az repos pr set-vote`, `az repos policy` and the
raw `az rest`/`az devops invoke` escapes, the union rather than this repo's
host; `git commit --amend` (it would fold
the implementation into the tests commit); `git reset --hard`, `git clean`,
`git branch -D`, recursive `rm`; pushes to `main`/`master`; bare `--force`;
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
more read of the same guard, never a poll, and the same shape (state, note,
resume point) as a stop between steps. Empty for any other reason still
fails.

The threshold is not flat, and the two windows do not share one: quota unused
when a window resets is lost, so each window's threshold ramps from
`limits.usage_pause_pct` to `limits.usage_ceiling_pct` over the last
`limits.usage_relief_fraction` of *that* window — the session against the
five-hour reset, the week against the seven-day one. The ceiling is validated
below 100, so relief never reaches the point where credits pay.

A pause writes `runs/paused.json` with a deadline and reason and schedules its
own resume — a `systemd-run --user` transient unit running `uv run abk tick`
at the moment the ramp would clear the current usage plus
`limits.usage_resume_buffer_pct`, else just after the window resets, else
thirty minutes later when nothing says when. No resume is scheduled more than
six hours out, so a weekly window resetting days away re-reads rather than
sleeping through everything. A `claude` call refused
mid-unit with a rate-limit message pauses too; a `claude` killed by a signal
leaves the unit `running` for the next tick's `reclaim_stale`, which commits
whatever the run left and requeues it at the step it was in.

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
authoring are separate processes with separate tools.

## State on disk

The planning repo's state directory (`planning.state_dir`, default `runs/`):

| File | What | Loss means |
|---|---|---|
| `units.json` | every unit: state, branch, PR, pushed and approved SHAs, feedback, `resume_from`, review rounds, history. The truth; the graph page is a view of it. | rebuilt work. Commit it. |
| `verified.json` | the last verification of each change and the units it covered. | a change verified again. |
| `planned.json` | hash and attempt count per change's specification. | one planning model call per change. |
| `prs-<repo>.json` | the poller's snapshot per repo. | the next poll only records; events in the gap are missed. |
| `own-posts.json` | ids of the pipeline's own PR comments and reviews. | a unit reworked over its own reply. |
| `paused.json` | the current pause, until when and why. | one usage check. |
| `usage-cache.json` | the live usage reading, three-minute TTL. | one endpoint call. |
| `tier2.lock`, `locks/` | the tier-2 queue lock; branch, repo and store locks. | nothing; kernel-released. |
| `<run id>-<repo>-<track>.md`, `tracked-issues.md` | the tracks' run logs and issue tracker. | history the tracks read. |

The tick commits nothing. The template `.gitignore` excludes only the locks,
`.env` and `.last-runs/` (the tracks' raw output); `units.json`, the run logs
and the graph page (`planning.graph_page`, rewritten on every store write) are
meant to be committed by the operator, and the tracks commit their own run
logs and `tracked-issues.md` by path. Unit worktrees live under the worktree
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
