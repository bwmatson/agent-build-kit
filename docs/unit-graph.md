# The unit graph

**Status: built.** The graph is the only engine. `graph/` holds the `UnitRun`
state, the node enum, the SQLite checkpointer with its allowlist and the
compiled graph, and `graph/unit.run_unit` runs a unit on it, over the
callables `wiring.build_runner` binds: `prepare`, `adapt`, `tests`,
`implement`, `checks`, `fix_checks`, `review`, `rework`, `tier1`, `tier2`,
`verify_base`, `push`, `open_pr`, `await_review`, `satisfied`, `held` and
`failed`, joined by the edges below. Before a step that starts work or leaves
the machine the nodes consult `upstream_incomplete` and the hold, and a unit
whose base moved is held. `await_review` and `held` are interrupts: a unit
waiting in review or held waits there holding no branch lock and no slot.
`resume_unit` delivers an event to a thread as a resume command and stops,
leaving the thread at the node the event routes to. A usage refusal before an
agent step interrupts the thread, and a run killed mid-node is resumed at that
node. A tick drives each unit through `run_unit`: it starts the unit's thread,
or resumes one a killed or paused run left (a `running` unit that has a thread,
whose branch no live process holds). The poller's events and `abk requeue`
reach a unit that has a thread through `resume_unit`, which runs no node but
the wait; the tick runs the thread in a slot. The first tick on this version
moves the units the previous one left in flight onto threads (see Moving the
units in flight). One difference from the old runner: the `chore:` commit of
uncommitted work before each review round is not made, as every step already
ends in its own commit. This document is what the implementation is specified
against: it says which part of the pipeline moved onto
[LangGraph](https://docs.langchain.com/oss/python/langgraph/overview), which
part stayed as it was, and how the two meet.

## Why

A unit's lifecycle is a graph, and was written as hand-rolled control flow.
`UnitRunner.run` (`pipeline/stack_runner.py`) branched on a recorded step
(`resume_from`, since removed) and decided which steps to run next. `checkpoint()` and
`record_step` persisted where it got to. `reclaim_stale` put a unit back after
its process was killed. And a dozen event handlers in `pipeline/events.py`
reach into the unit store to send a unit back, hold it, or move it.

All of this is ordinary workflow engineering:

- durable steps;
- resuming after a crash;
- waiting days for a person;
- routing on a step's result.

LangGraph is a widely used open-source framework for exactly that. Moving the
lifecycle onto it is meant to buy four things:

- **Less custom orchestration.** The framework owns step order, checkpoints
  and resume, so we stop maintaining our own.
- **A lifecycle that reads as a graph.** The nodes and edges are the
  specification, and they can be drawn.
- **A framework others already know.** A contributor or an agent who knows
  LangGraph can read and change the lifecycle without learning a bespoke
  engine first.
- **Observability per step.** Each node is a span, steps stream as events,
  and the state of any unit's run can be inspected.

The agents themselves are unchanged. They are still external processes
reached through the `AgentRuntime` seam (`docs/agent-runtimes.md`). LangGraph
orchestrates around them and does not replace them.

## The boundary: what moves, what stays

The open-source framework (MIT, 1.2.x at the time of writing) covers the
lifecycle of one unit well:

- checkpointed state;
- [`interrupt()`](https://docs.langchain.com/oss/python/langgraph/interrupts)
  to wait for input, with no documented time limit, and
  `Command(resume=...)` to continue;
- [durability modes](https://reference.langchain.com/python/langgraph/types/Durability),
  of which `"sync"` writes every checkpoint before the next step;
- [retry and timeout policies](https://docs.langchain.com/oss/python/langgraph/fault-tolerance)
  on nodes;
- [custom stream events](https://docs.langchain.com/oss/python/langgraph/streaming).

What it does not cover is everything above a single unit:

- scheduling across runs;
- locks and resource limits;
- a scheduler, crons or webhooks.

Those belong to LangSmith's paid deployment
([agent server](https://docs.langchain.com/langsmith/agent-server),
[cron jobs](https://docs.langchain.com/langsmith/cron-jobs),
[double-texting](https://docs.langchain.com/langsmith/double-texting)). So the
line falls where a unit ends:

| Moves into the unit graph | Stays abk code |
|---|---|
| Step order and branching (`UnitRunner.run`) | Choosing what starts: `ready_units`, the depth caps, `max_units_in_progress`, slot order, `max_concurrent_stacks` |
|  | Merge-gated dependencies (`merge_before`, from `Needs: … merged`), applied by `waiting_on`/`ready_units`: the dependent waits for the merge even in one repo and starts on the trunk; a merge gate is never a base, and a unit that had already started is told once when one is added, not disturbed. A failed or held unit requeued while the gate is unmet waits as `planned` with the cause `gated`, and the pass delivers the requeue in its mode once the dependency has merged |
| Where a run got to: the thread's position replaces `checkpoint()`, `record_step` and `resume_from` | The driver: the tick timer, `cmd_tick`, a pass's refresh loop |
| In-run state: review rounds, deferred follow-ups, pending replies and the comments they answer | Polling the forge (`pr_poller.py`): the source of events |
| Recovery after a kill: the tick resumes the thread | Branch locks, repo turns, the tier 2 lock |
| Waiting in review or held, and what `events.py` does to a waiting unit | Git and forge work: restack and adapt mechanics, the approved-commit push gate, the commit gate, the policy hook, forges, profiles |
| Stopping between steps for usage | The usage guard's decision (`usage_guard.py`), which a node asks |

### Who holds what

- **`runs/units.json`** stays the scheduling record. It holds each unit's
  identity, change, repo, tier, dependencies, state, branch, pull request and
  history. It is versioned beside the specs, the unit graph page is drawn from
  it, and `ready_units` reads it. What left it is in-run progress: where inside
  a unit a run got to, which is the thread's position, and the review rounds,
  deferred follow-ups, pending replies and the comments they answer, which are
  the thread's state. Two in-run fields stay, because something writes them
  with no run in progress: `approved` (the push gate and `build_restack` read
  and write it) and `predecessor_note` (`build_restack` writes it). A store that
  still carries a value in `review_rounds`, `deferred`, `pending_replies`,
  `person_comments`, `resume_from` or `classic_run` on a unit does not load: the error
  names the unit and the field, and that work must be finished or requeued first. The
  empty `resume_from` and `classic_run` the last release wrote on every unit are dropped
  on read.
- **The checkpoint** holds a run's progress. There is one LangGraph thread per
  unit, with `thread_id` equal to the unit id.
- **git** holds the work: every step that produces anything ends in a commit,
  as it does now.

One rule keeps these from drifting apart: **anything outside a running unit
changes that unit only by resuming its thread.** A merge that restacks a
child, a review comment, a requeue: each is a `Command(resume=...)` on the
unit's thread, which the graph routes like any other input. Nothing writes
into a waiting unit's state from the side.

## Priority

A unit carries a priority from 1 (most urgent) to 5, 3 unless a `Priority:` line
says otherwise. It is the most urgent of the groups the unit builds and is kept
once the unit has started. A unit's effective priority is the most urgent among
itself and every unit that waits on it, directly or through a chain, in any
repo; merged, closed and satisfied units, and units the round leaves out, do not
count.

## The graph

```mermaid
flowchart TD
    start((start)) --> prepare
    prepare -->|nothing of its own yet| tests
    prepare -->|resume at a step| resume{{resume point}}
    prepare -->|restack conflicted| adapt
    prepare -->|feedback waiting| rework
    adapt --> checks & rework & verify_base
    resume --> implement & checks & verify_base
    tests --> implement
    implement -->|commits| checks
    implement -->|nothing new| tier1
    checks -->|passed| review
    checks -->|failed, fix rounds left| fix_checks
    checks -->|failed, fix rounds spent| failed
    adapt -->|tests not accounted for| failed
    fix_checks --> checks
    review -->|approved, tier 2 unit| tier2
    review -->|approved| verify_base
    review -->|changes asked| rework
    review -->|needs a person, escalated| held
    implement & fix_checks & rework & review & tier2 & verify_base -->|upstream went back, base moved| held
    tier1 & push -->|upstream went back, base moved; on their conditions| held
    review -->|rounds spent| push
    rework --> checks
    tier1 -->|passed, no commits of its own| satisfied
    tier1 -->|passed, after a clean move, tier 2 unit| tier2
    tier1 -->|passed, after a clean move| new_comments
    tier1 -->|passed, on its base| verify_base
    tier1 -->|failed| failed
    tier1 -->|failed or changed approval after a move| prepare
    prepare -->|approved tip, tier 2 unit| tier2
    tier2 -->|passed| verify_base
    tier2 -->|passed, after a clean move| new_comments
    tier2 -->|failed| failed
    tier2 -->|failed after a move| prepare
    verify_base -->|base moved, clean| tier1
    verify_base -->|base moved, conflicts| prepare
    verify_base -->|on its base| new_comments
    new_comments -->|new comments| rework
    new_comments -->|nothing new, or no pull request| push
    push -->|host moved the branch| held
    push --> open_pr
    open_pr -->|base gone| prepare
    open_pr -->|rounds spent| held
    open_pr --> await_review
    await_review -->|rework| rework
    await_review -->|base moved| prepare
    await_review -->|hold| held
    await_review -->|merged / closed| finished((end))
    held -->|requeue| prepare
    held -->|release| await_review
    held -->|merged / closed| finished
    satisfied --> finished
    failed -->|requeue| prepare

    classDef agent fill:#fde68a,stroke:#b45309,color:#1c1917
    classDef forge fill:#bfdbfe,stroke:#1d4ed8,color:#1c1917
    class tests,implement,fix_checks,review,rework,adapt agent
    class push,open_pr,await_review,satisfied forge
```

Amber nodes run an agent. Blue nodes are where the unit meets the code host,
and the runner does that itself, in code, without an agent. Unshaded nodes are
git, tests and bookkeeping. Two nodes are not shaded but can call an agent: the
restack in `prepare` and `verify_base` hands a conflict it cannot settle to the
conflict resolver, and nothing else in them does.

The edges are the transitions the routers in `graph/` choose; their docstrings
are the reference for each condition. The nodes:

| Node | Does | Wraps (from `wiring.build_runner`) |
|---|---|---|
| `prepare` | Worktree, fetch, move the branch onto its base; picks the next node from what is on the branch and in state | worktree setup, `restack_onto`, `branch_commits` |
| `tests` | The tests-first commit | `run`, `commit` |
| `implement` | The implementation commit; nothing new against an exhausted window is a pause, not a failure | `run`, `commit`, `may_start` |
| `checks` | Tier 1 on the branch **before a reviewer is asked**, on the committed tree. Passing records the commit, so `tier1` after approval is not repeated on it | `tier1`, `commit` |
| `fix_checks` | Hands the failed checks' output to the builder, bounded by `limits.max_check_rounds`, then back to `checks`. Records no reply, as there is no reviewer to answer | `run`, `commit`, `may_start` |
| `review` | One review round; records the verdict, findings, follow-ups and the approved commit. After a person's rework it is also given their comments, quoted, each with the builder's reply or `(no reply)` | `run_review` / `run_rework_review` |
| `rework` | Addresses review or forge feedback and records the builder's replies | `run`, `commit` |
| `adapt` | Ports the old work onto a base it could not be rebased onto, and accounts for each test | the adapt agent, `check_test_decisions` |
| `tier1`, `tier2` | The test tiers. `tier1` is **not** run after a review: approval leaves the branch as `checks` judged it. It runs for a unit that produced nothing (judged on tier 1 alone) and on a branch moved cleanly onto a new base, before the push. `tier2` follows approval for a tier 2 unit | `tier1`, `run_tier2` |
| `verify_base` | The fresh-base check before a push | fetch, `fresh_base`, `restack_onto` |
| `new_comments` | Before the push, for a rework of a unit with a pull request, reads the notes and conversation again; those not in `seen_comments` and not the pipeline's own go back to `rework` as feedback, restarting the round counters; `open_pr` records the ids given to the agent so the poller ignores them | `fetch_comments` |
| `push` | Pushes only the approved commit | the push gate, `push` |
| `open_pr` | Opens or updates the pull request, posts replies and the PR body | `open_pr`, replies, labels |
| `await_review` | **Interrupt.** Waits for the forge: rework, a merge, a close, a hold, a moved base | — |
| `held` | **Interrupt.** Waits for a person: requeue, release, merge, close. The store state the hold leaves (`held`, or `planned` for a unit held before a step) is recorded by the node that held, not by this one, which runs again from its start when resumed | — |
| `satisfied`, `failed` | Terminal for this thread; `failed` waits for a requeue. A satisfied unit's thread is deleted, its groups ticked and an open pull request closed with the reason | `close_pr` for satisfied |

Between steps a unit is held, not stopped: before `implement`, `fix_checks`,
`review`, `rework`, `tier2` (unless the branch just moved), `verify_base` (and
`tier1` for a unit that produced nothing, and `push` when its rounds are spent)
the run asks whether its upstream went back for rework or its base moved or was
rewritten since `prepare` took the tip, and goes to `held` with the unit
`planned` if so. A step already begun is finished.

A base that moves before the push, a pull request refused for a missing base, a
failing tier 1 or tier 2 after a clean move, and a move that changed what review
approved all go back to `prepare` once (`rebased`), so the restack resolves under
the usage gate and review reads the result; a second time the unit is held
`planned` for the next tick, so a base that keeps moving cannot loop.

### Who touches the code host

An agent never changes anything on the code host. The runner does all of it,
at fixed nodes, from the agent's *output*:

| Direction | What | Where | Done by |
|---|---|---|---|
| Read | New comments, review decisions, labels, check results, mergeability | the poller, which resumes `await_review` | the runner (`pr_poller`, the forge) |
| Read | The reviewer's own words, fetched when a rework is queued | `events.on_rework`, saved as the unit's feedback | the runner |
| Read | A failing check's log | the same, for a failing-checks rework | the runner |
| Read | Its own pull request (`gh pr view`/`diff`, `az repos pr show`: the forge's read commands, nothing that writes) | the review | the review agent |
| Into the agent | All of the above | placed in the `rework` / `fix_checks` prompt as text | the runner |
| Write | The branch | `push`, the approved commit only, with a lease | the runner |
| Write | The pull request: open or update, body, state labels | `open_pr` | the runner |
| Write | Replies to review comments | `open_pr`, from the JSON the rework agent ends with (`{"replies": [...]}`) | the runner, after the push |
| Write | Closing a pull request whose work already landed | `satisfied` | the runner |
| Never | Merge, vote, approve, the raw API | refused on every repo by the policy hook and the ACP deny list | nobody; a person merges |

So the agent hands back structured text and the runner posts it. The rework
prompt tells the agent not to post and to end with that JSON, so the replies
describe the code as the reviewer will see it once it is pushed.

What an agent *may* run is narrower than it looks, and deliberate. A build agent
is allowed its forge's read commands (`gh pr view` and `gh pr diff` on GitHub,
`az repos pr show` on Azure DevOps) and nothing else on the host; the review
agent has only `git diff`, `git log` and `git show`. The runner puts the
feedback an agent needs into its prompt, and the read commands are there for
whatever the prompt does not carry, so an agent may look at its own pull request
when it judges that useful.

The tracks (health, improve, recommend, propose) use the same freedom: their
prompts tell the agent to run `gh pr view <url> --json state` to see whether a
PR in a follow-up list has merged. That read stays with the agent. The line that
matters is the one in the table: agents read the host as they need to, and never
change it.

### Checks before review

Tier 1 used to run once, after the reviewer approved, so a branch that did not
lint or type-check was reviewed twice over: once to approve it, and again after
the failure came back. The reviewer is also the more expensive model. Now every
route into `review` goes through `checks` first, including a rework: the
builder's fix for a reviewer's point can break the build as easily as the first
draft could.

A failure is saved on the unit as feedback (`tier 1 failed:` and the output) and
goes to `fix_checks`, up to `limits.max_check_rounds` times (3 by default;
`null` is no limit; 0 means no fix attempt, not no check: it is the only gate
before a review and a push). The count is per round of review: `checks` runs at
the top of each round and the budget starts again, so a rework that breaks the
build gets its own attempts. A fix that leaves the branch unchanged ends the
run whatever the limit, as asking again would be the same question of the same
tree. Only when the budget is spent does the unit go to `failed`, with the
output still saved, and `abk requeue --rework` is how it
gets another go with that output in front of the agent. A pause during a fix
keeps the saved failure, so the resume fixes what was found rather than finding
it again; a successful fix clears it, so a run stopped before its review does
not redo a fix that is already on the branch.

Nothing runs tier 1 after the review. A reviewer reports and the builder fixes,
so approval leaves the branch exactly as `checks` judged it. The branch is
checked again only when it changes: a clean move onto a new base
(`verify_base` → `tier1` → push) is checked before it is pushed, and a move with
conflicts goes through `adapt`, which accounts for its own tests and then back
through `checks` and `review`, since the resolution rewrote the commit that was
approved.

The nodes wrap the callables `wiring.build_runner` already builds. None of the
agent, git or forge logic is rewritten; what changes is who decides what runs
next. Node names are an enum, also used as the routers' return values, so a
misspelled edge fails when the graph is compiled, not in the middle of a run.

### State

The state is one pydantic model, `UnitRun`: the in-run progress that used to
sit in the unit store, plus what routing needs:

- **identity:** the unit id, its groups, its change;
- **progress:** the review rounds so far (each round's findings and the
  builder's response), the approved commit, deferred follow-ups, pending
  replies, the predecessor note;
- **step results routing reads:** commits this run produced, the last verdict,
  tier results, why a run stopped;
- **the last event received,** so a resumed node knows why it is running;
- **the running agent's session id,** written as soon as the runtime reports it
  and cleared when the node completes (see Session capture and resume);
- **what the build path routes on:** the base the unit is on once `verify_base`
  moved it, the commits on the branch when `prepare` finished, the branch's tip
  when the last node finished (what a re-run compares with), whether feedback
  was waiting at the start, the fix rounds and the review round so far, and
  whether the checks passed, the branch is empty or `verify_base` moved it, the
  base's tip when `prepare` began, whether it is a tier 2 unit, the restack that
  could not be merged (for `adapt`), whether the review rounds are spent, tier 2's
  results, whether to go back to `prepare` and whether it already has once;
- **why a run is held:** the detail, the state the store is left in and its note;
- **how the run ended:** the status, detail and pull request `RunOutcome` reports.

Updates are partial: each node returns only the fields it changes. Anything a
person reads (state, pull request, history) is also written to `units.json`
by the node that changes it, as today. The graph diagram and `abk status`
keep working unchanged.

## Events become resume commands

The poller stays exactly what it is: snapshot, diff, report. What changes is
the handler. Today it rewrites the unit in the store. Instead it resumes the
unit's thread with a command:

| Event | Command | Routed by |
|---|---|---|
| A review asking for changes, a new comment, `agent-rework`, newly failing checks, a merge conflict | `rework{reason, kind, feedback, source}` | `await_review` → `rework` |
| The parent merged, or the base was rewritten | `base_moved{new_base}` | `await_review` → `prepare` (a running unit sees it at its next node) |
| `agent-hold` | `hold` | → `held` |
| `agent-hold` removed | `release` | `held` → `await_review`, for a hold the label made |
| Merged | `merged` | → end; `units.json` records the merge, and a child waiting in review (stored `in_review`, within the rebase cap) is sent `base_moved{new_base}` and its PR is retargeted at once, instead of being restacked by the handler; every other child, with a thread or without, is handled by the handler itself (restacked, held for depth, or left alone) |
| Closed unmerged | `closed` | → end |
| `abk requeue` | `requeue{mode}` | `held` / `failed` → `prepare`. `resume` (the default) goes back where it stopped; `restart` drops the saved failure and rounds but keeps the branch's commits (it does not start a fresh thread); `rework` keeps the work and the saved failure, and so enters at the agent with the failure in hand (`fix_checks` for a failed check) |

A delivery runs only the wait node's own work, the store writes and the event in
the state, and stops there (`interrupt_after` on the waits): it never runs the
next node. The unit is left `running` with its thread positioned at the routed
node (`rework` for a rework, `prepare` for a moved base or a requeue), so
`resumable_units` offers it to the scheduler and the tick runs it in a slot like
any thread with work to do. No event handler, poll or `abk requeue` runs an
agent, a check or a push outside a slot, so `max_concurrent_stacks` holds.

An event for a unit whose thread is mid-node is kept and delivered once the
thread waits. A run holds the unit's branch lock from reading the thread's
position until it returns at a wait or the end (`build_graph`), and a delivery
holds it while it acts (`resume_unit`); there are no others, so a thread that is
mid-node always has its lock held, and the lock is what says a run is in
progress. `resume_unit` raises `BranchBusy`, with the thread untouched, when
someone else holds it. It raises it too when the thread has a node still to run,
because it was cut short, paused for usage, or already routed by an earlier
event: such a thread is not carried on inside the handler, the tick resumes it in
a slot, and the event is delivered once it waits. The event handlers and `abk
requeue` treat `BranchBusy` as the poller's deferral: the event is kept and the
poller reports it again. An event for a thread that has ended (`NotWaiting`) is
not delivered, and the handler does what the event handler acts on the store alone: it holds the unit
for a `hold`, saves the feedback and plans it again for a `rework`. `await_review`
and `held` are `interrupt()` calls, so a waiting thread's next node is the wait.
`merged` and `closed` route to the end and the thread is then deleted. A
`requeue` of a thread that ended in `failed` is delivered as if from `held`. A
`rework`, `hold` or `base_moved` for a held unit is not delivered: a person has it, and the poller keeps a comment unseen until the unit is released.
A merge sends `base_moved`, with the new base as its reason, only to a child
waiting in review (stored `in_review`, within the rebase cap), and that thread's
own `prepare` moves the branch while its PR is retargeted at once. Any other
child is handled by the handler itself, as above. If the delivery finds the child's
branch busy, the thread is not told and the handler logs that; the merge is not
redelivered.

A node that raises out of a run leaves its thread at that node while the build
records the unit `failed` (or `held`). Nothing will run that node, so a delivery
treats such a thread, with the lock held, as an ended one: a `requeue` positions it
at `prepare`, and any other event is `NotWaiting`, and the handler acts on the store as above.

## Durability and idempotency

- **Checkpointer:** `AsyncSqliteSaver` with WAL, in the state directory beside
  the unit store, and `durability="sync"`: the host can lose power at any
  moment. It is SQLite rather than a database server: one tick process writes
  it, with a handful of threads in flight, and a server would add the failure
  modes the pipeline exists to work through.
- **Serialisation:** an explicit `allowed_msgpack_modules` list for the state
  model's types, with strict msgpack otherwise. Checkpoint deserialisation has
  had remote-code-execution advisories (fixed in langgraph-checkpoint 4.1.1),
  and a type left off the list fails a resume, not a build. A test loads a
  checkpoint holding every state type.
- **A node killed partway re-runs from its start.** That is LangGraph's
  contract, and it is the same as today's step boundaries. So each node first
  checks git:
  - commits already on the branch from this step;
  - the pushed commit;
  - an open pull request.
  It does nothing twice: an agent node compares the branch's tip with the one
  its predecessor recorded, `push` always goes through the push wiring, where a branch the host moved is
  caught (pushing a commit the remote already has changes nothing), and
  `open_pr` runs again whole: the real call finds the branch's pull request and
  updates it instead of opening a second. A killed agent process leaves uncommitted work in the worktree; nothing
  commits it as `wip:`. Each agent node records its name in the thread state
  (`running_node`) before its agent starts and clears it when it completes, so a
  kill leaves it behind even when the runtime named no session. A dirty tree at
  the node named there, if it is one that edits (tests, implement, fix checks,
  rework, adapt; never review), with no live process on the branch, is that node's own:
  the re-run carries on over it. A recorded session is continued with the
  interruption prompt and nothing more; a new session (none recorded, or the
  runtime cannot continue it) is told in its prompt which paths are uncommitted
  work from an interrupted run, to be reviewed and finished. The node's commit
  includes them. Any other dirty tree (no record, another node's, a node that
  runs no agent, a hand edit) holds the unit with the cause `dirty_worktree`,
  the paths and a request to commit or remove them; nothing is cleaned, and
  `abk requeue` after the tree is clean resumes a park at an agent step at that step
  (`parked_node` in the thread state), with that node's inputs as they stood, a
  rework's feedback included; a park anywhere else, and `abk requeue --restart`,
  begin again at `prepare`. A requeue while the tree is still dirty leaves the unit
  parked. The dirty-tree rule reads the unit's chat lease first (see Chat in
  [architecture.md](architecture.md)): a lease whose server has gone while the lease is marked as
  holding changes means the files are a chat's, not a killed run's, so the unit is held
  with the cause `attached` and nothing is committed or continued, whatever
  `running_node` says; a lease held by a live process leaves the unit alone; a lease marked
  as holding a commit that was made and not delivered is a delivery to finish, not changes.
  Only with no lease at all does a recorded `running_node` make the tree the node's own.
- **A killed run is resumed, not requeued.** The thread's next node is the
  one that was running, and the next tick carries on from it with no new
  input. The unit stays `running`, and the tick resumes it unless a live
  process holds its branch. Nothing requeues it, and nothing commits what it left.
- **`review` and its rounds.** A round's findings are returned in the node's
  own update (`review_rounds` in the thread's state), not written to the unit
  store first, so a kill before the checkpoint leaves no half-recorded round: the
  re-run asks the reviewer again and records the round once. An approval is
  the exception: `weigh_review` records the approved commit on the unit
  (`approved`) as it is read, and a re-run records it again.
- **Timeouts kill the process group.** A node's `TimeoutPolicy` cancels its
  task, and cancelling a task does not stop a child process. The runtime call
  inside a node owns the agent's process group and kills it on cancellation.
- **Threads end when units do.** A thread is deleted when its unit merges, is
  closed or is satisfied. An unfinished unit is exactly a thread that still
  exists.

## Host outages

A step that gives up because the code host is unavailable (`HostUnavailable`) is not
a failure. The unit goes back to `planned` with the cause `host_unavailable`, the step
and the error text, and its thread stays at the node. The running pass readmits it
once its backoff has passed (1, 2, 5, 10, then 30 minutes by consecutive parking, from
when it was parked) and logs how long remains until then; a success resets the count.
Any other exception fails the unit and records its type, text and step.

On a fresh start `prepare` notes whether the approved commit is the pushed head
(`pushed_head`) and whether a pull request exists (`opened`). With the former, and no
pull request or unposted replies (owed replies count only when no feedback is saved, so a
requeue for rework still reworks), `after_prepare` routes straight to `open_pr`, before
tier 2, review or rework from saved feedback. Known limitation: a unit started fresh this way
has no tier 2 snapshot in its run state, so the pull request it opens lacks the tier 2 result
section.

## Usage pauses

Before an agent step (`tests`, `implement`, `fix_checks`, `review`, `rework`) a
node asks the usage guard. When the guard refuses,
the node interrupts with `{reason, until}`, `until` being the guard's resume
time (`UnitRunner.resume_at`); it does not put the unit back to `planned`: the
unit stays `running`, with its thread interrupted before the agent node, and
the run's outcome is `paused`. The tick resumes every thread interrupted that
way once the guard allows: it asks again on every tick, as the pause marker
does (`pipeline/pause.py`). The graph page draws such a unit as `running`. A step is never interrupted while it runs:
interrupts happen only at node boundaries.

## Session capture and resume

An agent node, `review` included, passes `on_session` to the runtime, which
calls it once, on the init event that names the session, with the agent's
session id as soon as it knows it; the id is written into the thread's
state at once, so a node killed mid-agent leaves it behind. The node's
completion clears it. When the next tick re-runs a node that has one, the node
asks the runtime to continue that session with a prompt saying the process was
interrupted and to re-read the worktree before trusting its memory. A runtime
that cannot (`supports_session_resume` is false, or the session is gone or
refused: `SessionUnavailable`) is not an error: the node runs from its start in
a new session and says so in the run log.

A completed build node also leaves the role's latest session in the state: its
id, runtime, model, node, round and the branch's head when it ended, and
`build_model`, the model the first build node ran on. With `session_reuse` on
for the role (`build` by default), one resolution step before the agent call
chooses between the three ways a node can speak:

1. The node's own interrupted run (`session_id` set): continue it with the
   interruption prompt, as above.
2. The role's latest session, when the runtime that recorded it is the one
   running and can resume, and its recorded head is still readable in the
   worktree: continue it on the model it recorded, with the node's
   **continuation prompt**, which carries only what is new (the failure output,
   the review findings, the predecessor and the conflict) and drops the change
   path, task groups and boundary notes the session already holds. When the
   branch's head is not the recorded one, the prompt begins with the two hashes
   and an instruction to read what changed, never a log or a diff. After
   `adapt`'s reset the old work is under `refs/spec-driven/pre-adapt/<unit>`,
   which the prompt names.
3. Otherwise, or when the resume raises `SessionUnavailable` (including a
   context overflow, which Claude Code reports as a prompt too long): a new
   session with the full prompt on the node's model, and a line in the run log
   saying why.

`tests` always starts the build session; `implement`, `fix_checks`, `rework`
(whether its feedback came from a review round, failing checks or a comment on
the pull request) and `adapt` continue it, always on the model it recorded.
`review` never continues a build session or an earlier review round's session:
its judgement does not share the author's context. The follow-up rounds of
`adapt`, which put its test accounting back to the agent, continue the session
the port ran in, and the session recorded for the build afterwards is always the
one that did the port. A node killed during a continuation resumes that session
on the model it recorded.
`fix_checks` starts a new session on `build_model` (the configured implement
model when none is recorded), and a continued session runs on the model it
recorded. A node that completes without
its call reporting a session, after one was started and killed, drops the
role's recorded session rather than keep one that no longer describes the
branch.

## Concurrency

- One tick process runs the threads on asyncio, at most `max_concurrent_stacks`
  executing at once. A thread waiting in an interrupt costs nothing.
- The scheduler is unchanged in what it decides. `ready_units` picks what
  starts, and existing work goes first. What it does changes: it **starts** a
  thread for a new unit and **resumes** threads that have something to do (an
  event, a usage pause that has cleared).
- A run holds the unit's branch lock from reading the thread's position until
  it returns at a wait or the end, and the nodes under it do not take it
  again: there is one lock mode, the run's. A thread waiting for review holds
  no lock, as its run has returned, so an event handler never finds the unit
  busy for days. A delivery takes the lock only for its own short write.
- Nothing but a slot runs a node. A poll's event delivery, `abk requeue` and
  the scheduler's refresh run no agent, check or push: they position the
  thread, and the pool runs it.
- Repo turns and the tier 2 lock are taken inside the nodes that need them, as
  the wrapped callables do now.

## Observability

- **A span per node,** with the unit id, change and step as attributes, and the
  round for the steps that go in rounds. It sits below the unit's span and the
  tick's, and agent spans nest under it; each node also records its duration
  and outcome (docs/architecture.md, Telemetry).
- **A span record per node** in the usage ledger: UTC start and end, duration,
  outcome and round, written when the node returns or raises. A usage pause
  (`usage_pause`) and the wait for a build slot (`slot`) are recorded as waits
  with their bucket, and each tier 1 command with its duration
  (docs/architecture.md, Spans).
- **Progress lines** reach the unit's run log (`runs/unit-logs/`) through
  `RunLog.emit`, called by the nodes. Stream events (`get_stream_writer`) are
  not built yet.
- **The graph itself** is drawn from the compiled graph into this document and
  the docs, so the diagram cannot drift from the code.
- **LangSmith tracing** is supported by the framework, optional, and off by
  default. Nothing in the pipeline depends on it.

What stays in the store, and why: `approved`, because the push gate and
`build_restack` read and write it with no run in progress; `predecessor_note`,
because `build_restack` writes it the same way. `build_restack`
no longer writes a resume step: a restacked child goes `planned` with a note,
and its run's `prepare` decides from the branch. `in_progress` and the start
rank judge that a planned or unplanned unit has been started from what a run
writes: a recorded `branch`, a `pushed` or `approved` commit or a `pr`.

`UnitRunner`'s control flow, `checkpoint()`, `record_step` and `reclaim_stale`
are gone, and so is the `ABK_ENGINE` setting; it was never released, so it has
no deprecation window. The callables in `wiring.py` and everything they reach stay.

## Testing

- **Nodes** are tested alone with the same injected fakes the stack runner's
  tests use today.
- **Paths** are tested through the compiled graph. The stack runner's
  scenarios are ported one for one (build, review rounds, rework, adapt,
  satisfied, holds, spent rounds, moved bases, and the check before review:
  passing, fixed and re-checked, budget spent, no fix attempts, re-checked after a
  review rework, a clean and a conflicted move after approval), so the migration is checked against the behaviour it replaces.
- **Resume** tests:
  - kill the process mid-node and resume the thread in a new process, so that
    node re-runs and does nothing twice;
  - deliver an event to a thread that has waited across a restart, and one
    that arrives during a node;
  - a usage interrupt cleared by a later tick;
  - a node killed mid-agent resumes its recorded session, or falls back to a
    new one;
  - a checkpoint holding every state type loads under the allowlist.
- **Acceptance:** one real unit built end to end through the graph, reviewed,
  pushed, opened, then resumed by a real review comment. The live-agent tests
  read the run log as the graph writes it: lines are `<unit>: <node>: …` with
  the node names from `graph.state.Node`, and a failing tier 2 leaves the tail
  of its output there, under the `tier2` prefix.

## Dependencies

`langgraph` and `langgraph-checkpoint-sqlite` become core dependencies, pinned
together; the checkpoint packages have moved a major version within a year.
The framework brings `langchain-core`. Nothing else from LangChain is used:
there are no LangChain models, prompts or tools, since agents are reached
through `AgentRuntime`.

## Display statuses of a running unit

The store holds `running` for every unit an agent is working on. The graph, `abk status` and the
pull request's state label derive a finer name: `rebasing` when the unit was sent back for a
conflict, a moved base or a restack conflict or deferral, `reworking` when it is answering review
or check feedback, and `running` otherwise. A pull request is a draft while its unit is `running`
or `planned` and ready when it is `in_review`.

## A unit in review follows its predecessor

After each fetch and poll, a unit in review whose same-repo predecessor's branch is changing is
set back to `planned` with the cause `upstream_went_back`, keeping its approval, branch and pull
request. A branch is changing when the predecessor is not in review, merged or satisfied and it
holds a commit beyond its last pushed head, is rebasing, or is itself planned for a changing
upstream or a moved base. A chain moves in one pass; a unit with a deferred restack, or whose
branch is busy, is left for a later pass. When the predecessor is back in review the unit is
released and restacks onto its new head; an unchanged head restacks nothing.

## The checking status

A unit stored as `in_review` reads `checking` while any check on its pull request is pending, or
while the pull request has none within `limits.checks_register_seconds` of the unit's last push
(`pushed_at`, written with `pushed`). It reads `in_review` once its checks have passed, or the window
has ended with none. The status is derived from the poller's snapshot (`prs-<repo>.json`), never
stored, and counts as in review for scheduling, queue places and dependents. `abk status`, the graph
and the pull request's state label show it, and the poll that records a pull request's checks moves
the label between `in-review` and `checking`. The web UI still shows the stored state.
