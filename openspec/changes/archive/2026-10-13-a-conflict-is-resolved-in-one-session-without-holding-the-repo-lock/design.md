# Design

## What was checked, and where

Read-only, `git fetch` then `git show origin/main:<path>` in the agent-build-kit checkout (origin/main at `c2a76e1`). Paths are under
`src/agent_build_kit/`; line numbers are those of that commit.

**The move and the resolver (`pipeline/restack.py`).**
- `move_branch_onto` (247) runs `git rebase --onto <new base> <old base> <branch>` with `repo` as the directory (272-281) and rerere
  switched on per invocation (`RERERE`, 63; `git()`, 66). A clean rebase returns `Moved` (282-283). With no resolver it aborts and raises
  `RestackConflict` (285-291).
- With a resolver it reads the conflicted paths (293), derives `must_keep` (`derive_must_keep`, 173-204: up to `MAX_MARKERS = 3`
  identifiers of at least five characters that the branch added and the old base did not have), and works out which paths arrived with a
  replayed resolution from git's own notice (297, `_replayed_files`, 230). It fills `RESOLVE_PROMPT` (111-129) and `REPLAYED_NOTE`
  (131-141) and calls `resolve(prompt, cwd=repo)` once (316).
- The agent's refusal, interruption or an outage aborts the rebase and re-raises (317-322); any other failure aborts as a conflict
  (323-324, `_abort`, 240-244). The result is then checked: a conflict marker left in a conflicted file aborts, and `git rerere forget`
  is called first for every marked path that carried a replay (326-346); a `must_keep` token absent from every conflicted file aborts
  (348-354); a replayed path the agent edited gets `rerere forget` so the override is what is cached (356-363). Then `git add -A` and
  `git rebase --continue` (365-371); a failed continue aborts. The result is `Moved(sha, resolved=files)` (373).
- **The resolver checks two things only: markers and the unit's own tokens.** It does not look at the unit's tests (grep for tests in
  `restack.py` finds none). "Tests missing or changed" is the adapt step's accounting check (`tests_needing_decision`,
  `check_test_decisions`, `pipeline/stack_runner.py` 1153, 1165), run after the port.
- `claude_resolver` (643-664) builds an `AgentRequest` with tools `Read Edit Write Grep Glob` (`RESOLVER_TOOLS`, 640), no model, no
  session and no recording callback, and runs it on the active runtime. So the resolver writes no ledger row and shares no session.
- `resolved_move` (524-566) wires the context and `claude_resolver`; the stack-move handler and a unit's resume both call it.

**The in-run restack (`pipeline/wiring.py`, `graph/nodes.py`).**
- `build_restack_onto` (2160) returns `restack_onto(tree=, branch=, base=, unit=, resolve=True)`. It does nothing when the base is
  already an ancestor (2186), finds the unit's own start with `own_work_starts_after` (2122), moves with `resolved_move`, or with
  `_move_without_resolver` (2153) when `resolve` is false, and turns a `RestackConflict` into `Restacked(conflict=..., old_tests=...)`
  (2211-2221). A clean move with an unchanged diff on an approved head keeps the approval (2225-2230).
- `prepare` (nodes.py 944) calls `restack_onto` with the resolver (967). `restacked.conflict` returns the `conflict` state (981-982) and
  `after_prepare` routes it to `adapt` (2167-2168). A resolved move is recorded with a predecessor note (984-995).
- `adapt` (1020-1119) resets the branch to the base keeping the old work under `refs/spec-driven/pre-adapt/<unit>` (1036-1040, only when
  the head is still the one `prepare` saw), runs `ADAPT_PROMPT` on the rework model with `ADAPT_CONTINUATION` as the follow-up for a
  continued session (1042-1062), commits (1065), computes the tests to account for (1069-1072), and asks again up to
  `limits.max_adapt_rounds - 1` times, continuing the port's session (1076-1096, default 2, `config.py` 349). An incomplete accounting
  records the problems as the unit's feedback and stops the unit (1098-1109).
- `verify_base` (1767) fetches, works out the base afresh, and calls `restack_onto(..., resolve=False)` (1785-1791): "a resolution here
  would run outside the usage gate". A conflict or a resolved move goes to `rebase()` (526-535): the first time it returns
  `restack=True, rebased=True`, and `after_verify_base` (2236-2241) routes that to `prepare` **in the same run**; a second time it holds
  the unit `planned` with cause `base_changed`. So a conflict found before a push is already resolved, under the usage gate, by the
  `prepare` that follows in the same run. The plan's wording "held and resumed later" describes the log line, not a separate run.
- **The in-run restack takes no repo turn.** `unit_repo_turn` (wiring.py 2643) wraps only `worktree_in_turn` (2651) and `push_in_turn`
  (2655), and the fetch takes it (2743). `restack_onto=build_restack_onto(store, repo=repo)` (2714) is bound unwrapped. This answers the
  plan's open question: the unit-resume path does **not** take the turn at all.

**The stack-move handler and its turn (`pipeline/events.py`, `cli/pipeline.py`).**
- `build_restack` (events.py 1354) sets `cwd = worktree if worktree.exists() else repo` (1404); `cwd` is used for adopting a host head
  and for tier 1, while the move itself is called with `repo` (1480-1489), that is **in the repository's own checkout, not the unit's
  worktree**. This corrects the plan's step 7: the handler's rebase runs in the repo's checkout (switching it to the branch, or refusing
  when the branch is checked out in a worktree), and only the checks run in the unit's worktree. `RestackConflict` leaves the unit
  `planned` with cause `restack_conflict` (1495-1506); a rate limit, interruption or outage leaves it `planned` with `restack_deferred`
  (1507-1531).
- `repo_turn` (`cli/pipeline.py` 2738) is `file_lock(<state>/locks/repo-<repo>.lock)`, an `flock` that waits (`pipeline/file_lock.py` 25).
  `build_stack_moves` (2759) gives the handler `move=at_path(in_repo(resolved_move))` (2807) and `push=at_path(push_with_lease)` (2810),
  where `at_path`'s `in_turn` (2773-2776) takes the turn around the whole call, so the move holds the turn through the resolver.
  `remove_worktree` and `delete_branch` are `named(...)` the same way (2812-2813).
- The rest of `build_restack` (adopting a host head, tier 1, the push) runs as separate calls; tier 1 is outside the turn.

**Sessions (`graph/nodes.py`, `config.py`, `docs`).** `SESSION_ROLES` (nodes.py 165-172) puts `tests`, `implement`, `fix_checks`, `rework`
and `adapt` in role `build` and `review` in `review`. `session_reuse` defaults to `{"build": True, "review": False}` (`config.py` 746).
`Node.agent` (nodes.py 537) continues a killed run's session, or the role's latest session when a `follow_up` is given, or starts
a new one on `model`. `docs/configuration.md` 150 says the rework model runs restack conflict resolution and adapt "when they start a
new session", while `claude_resolver` sets no model.

**Worktrees (`pipeline/workspaces.py`).** `prepare_worktree` (191) reuses an existing worktree and refuses a dirty one (`DirtyWorktree`).
`prepare_detached` (240) makes a checkout of a ref on no branch under `<root>/<repo>/<name>`. `remove_worktree`
(257) refuses a dirty tree. `worktree_path` is `<root>/<repo>/<branch with non-alphanumerics as _>` (124).

**What is guarded against a half-finished rebase today.** Only `_abort` and the `except` paths inside `move_branch_onto` (the module
docstring, 21-22); and `prepare_worktree`'s dirty check, which reads `git status --porcelain` and so sees an unmerged tree on the next
run. No scan for `rebase-merge` or `rebase-apply` exists (grep over `src/` finds none). A hard kill of the process during the resolver
window leaves a rebase in the worktree today; this change neither widens nor closes that window.

**Docs read:** `docs/architecture.md` 280-312 (restack and adapt in the build's step 2), 455-475 (the pre-push check and its once-per-run
loop), 612-624 (the handler's turn: "A restack's rebase runs in the repo's own checkout and holds the turn to the end, conflict resolver
included"), 728-760 (the restack paragraph, rerere, the check list); `docs/unit-graph.md` 150-160, 203-211, 225, 243-246, 311; `docs/agent-runtimes.md` 85, 104;
`docs/configuration.md` 150-160, 250.

**UNVERIFIED**, marked where each is used below:
1. That git's own final ref update at the end of `git rebase` is a compare-and-swap against the rebase's recorded original head. The
   design does not rely on it: the pipeline checks the branch ref itself under the turn before it continues.
2. That `tests_in` and `tests_changed` (`wiring.py`) can be read against a worktree paused mid-rebase with the resolution staged. Rung
   a's third guard needs it.
3. That a runtime resumes a session with a request whose tool list differs from the previous call's (the resolver rungs run with the
   resolver's tools, rung c with the build tools). `adapt`'s follow-ups already resume with the same tools.
4. That `file_lock` is not re-entrant in one thread, so no code path may take the turn while holding it. The design takes the turn only in
   short, separate, non-nested blocks.
5. Which model a resolver request runs on today (docs say the rework model; the request names none).
6. How often a branch with no unit worktree is checked out in the operator's own checkout while a restack runs.

## Decisions

### 1. One conflict step: three rungs, one session

**The step is the resolver calls of `prepare` plus the existing `adapt` node, tied by the build session.** The alternative, one new
graph node that does the reset, the port and the accounting itself, would move the commit gate, the accounting loop and the unit-state
writes out of `adapt` for no gain. Rung c's machinery needs the node (its `self.agent`, `r.commit`, `r.store`), so rungs a and b are
agent calls made from inside the restack, through the node's agent machinery, and rung c is the `adapt` node entered when they fail. What
makes it one session is the `build` role: the restack step is added to `SESSION_ROLES` as a `build` node, so with `session_reuse.build`
on (the default) the first rung continues the unit's build session or starts it, and `adapt` then continues it, as `adapt` already
continues the build session after `rework`.

**Rungs.** The first prompt (`RESOLVE_PROMPT`, rewritten) carries both intents, the conflicted files, the replayed note, the diff, the
changelog rule, and the ladder in words:

- a. Change only the conflicting hunks, and only the files that conflict, so that both intents survive.
- b. If the pipeline tells you its checks failed, you may change the unit's other files that depend on the conflict (callers of a
  renamed function, a test that exercised a removed argument), and nothing else.
- c. If a and b cannot work, say so by leaving the conflict markers in place. The pipeline will then keep this unit's old work under a ref,
  reset the branch to the new base and ask you to port the work; the same session continues.

Between rungs the pipeline checks and acts; the agent does not decide the escalation by itself except by leaving markers, which today's
prompt already tells it to do when the intents contradict ("stopping is better than guessing").

**Checks per rung.** Each rung's call ends and the pipeline runs, in this order:
1. No conflict marker left in a conflicted file (today's check, restack.py 326-346).
2. Each of the unit's own tokens (`derive_must_keep`, 348-354) is still in the conflicted files.
3. **New:** none of the unit's own tests (`old_tests`, from `defined_tests_in_range`) is missing from the paused tree. Only *missing*
   escalates here, not *changed*: a conflict inside a test file legitimately changes tests, and "changed" would make rung a impossible
   there. A changed test is still seen by review (the predecessor note already asks the reviewer to check the unit's tests still fit).
   UNVERIFIED (2): whether the paused, staged tree can be read by `tests_in`; if not, this check runs after `--continue` and a failure
   resets to the old head (the head `prepare` saw) before rung c, which is where rung c starts from anyway.

A failed check puts the failing check's own message back to the agent in the next rung's continuation prompt (the same practice as
`ADAPT_FOLLOWUP_PROMPT`). A failure after rung b means rung c. A rung that raises a rate limit, an interruption or an outage does not
escalate: the rebase is aborted and the exception propagates exactly as now (restack.py 317-322).

The ladder is two resolver rungs, not more: a third widening rung would be another way for unreviewed edits to enter, and a rung that
costs a call without a new capability is the thing this change removes.

**Edits beyond the conflict.** Rung b allows them, and `Moved.resolved` names them with the conflicted files (union), so the predecessor
note review reads says which files the resolution touched. A rung a that edited another file is not refused; it is recorded the same
way. Refusing would bring back the abort-and-start-again this change removes, and review already reads the result: any move that needed
resolution is reviewed before it is pushed (`unit-base-freshness`).

**Rung c is today's adapt, unchanged in what it does.** It keeps the old work under `refs/spec-driven/pre-adapt/<unit>`, resets,
asks for a port with keep/adapt/retire decisions for the tests the replay left uncertain, runs `check_test_decisions`, and puts the
problems back up to `max_adapt_rounds - 1` times, all in the continued session; `ADAPT_CONTINUATION` carries what the agent needs
(the answer format) and gets one sentence saying which rungs already failed and why. A session that cannot be continued (the runtime
cannot resume, the recorded head is unreachable, or the context overflowed) starts a new one with `ADAPT_PROMPT` in full, with no error,
exactly as `adapt` behaves today and as the session-reuse spec already requires.

**When reuse is off or the session is unusable at rung a:** each call is its own session, and the prompt of every call repeats the ladder
and the failing check, so the order still holds; only the memory is lost. Say so in the docs.

**Model.** A new session starts on the rework model (`docs/configuration.md` already says so for the resolver; `adapt` runs on it today);
a resumed session keeps the model it started on (session-reuse, unchanged). This changes the resolver's model from "none named" to the
rework model, UNVERIFIED (5) as to what it was.

**Usage gate and where it runs.** The step runs in `prepare`, which a run reaches at its start and again from `verify_base` through
the existing once-per-run loop (`after_verify_base`, nodes.py 2236-2241). `verify_base` therefore keeps `resolve=False`: its restack
aborts a conflict and loops to `prepare`, where the agent step runs. This differs from the brief's "inside `verify_base`" on purpose:
the conflict is found in `verify_base` and resolved in the same run, one node later, which already is "in the run that finds it", and
putting an agent call inside the pre-push check would put it past the gate comment at nodes.py 1783-1784 ("outside the usage gate").
A usage pause still defers the agent step: the rebase is aborted under the turn and `AgentRateLimited` propagates as at 317-322, so
the unit is paused and the move is retried when the pause ends. A clean move needs no agent and proceeds in the same pause.

**The once-per-run rule stays.** `rebase()` (nodes.py 526-535) lets one loop back to `prepare` per run and holds the unit `planned` on
the second. What changes is only what the first loop does: it now settles the whole conflict (a, b, or c) rather than a resolver
attempt followed by a node that may or may not run. The rule exists for a base that keeps moving and does not depend on how a conflict
is resolved. A conflict resolved by the step does not count as a second hold. A hold remains when the last rung fails: an incomplete
accounting still fails the unit as today (`adapt`, nodes.py 1098-1109), and a rate limit or outage still leaves it planned.

**The handler path.** The stack-move handler resolves a conflict it meets with rungs a and b only, in its own session (a unit with
no run has no thread to record a build session in, UNVERIFIED how the store could carry one), and leaves a still-failing conflict
`planned` with `restack_conflict` as now. The unit's next run runs the whole ladder from rung a in its build session. This repeats rungs
a and b once; making the run start at rung c would need the handler to leave the failure on the unit in a form `prepare` reads (the cause
is overwritten when the run starts), and it is a smaller cost than the added state. Recorded here as a known inefficiency. The handler's
calls are recorded as the `restack` node with the unit being moved.

**Recording.** The step's calls are recorded through the shared helper of `every-agent-call-is-recorded` as node `restack`, one row per
agent call (a rung that is asked again is a second row), with the unit being moved, `change` and `repo` filled. Group 2 therefore
`Needs:` that change's group 1.

**Replayed resolutions.** All four existing rules survive:
- A replay is written to the tree and left unstaged; the paths that carry one are in the first prompt (`REPLAYED_NOTE`).
- The agent stages it by leaving it unchanged (the pipeline stages), edits it (the edit replaces the cache entry through `rerere
  forget` at 356-363), or plants a conflict marker.
- A marker in a replayed file is a rejection: `rerere forget` runs for that path before anything else happens (336-341), so the next
  sibling sees the conflict itself. **What changes:** the rejection no longer aborts the move for a person; it fails the rung, and the
  next rung or rung c carries on. Rung c resets the branch, so nothing replayed survives it.
- Every replayed path is staged by an act of the step, never by git: the pipeline's `git add -A` at 365 follows the checks.

### 2. The repo's turn per phase

**What the turn protects, and what a rebase writes.** The turn exists because the worktrees of a repository share one `.git`, where git's
own locks (`packed-refs.lock`, `refs/heads/<branch>.lock`, `config.lock`, a worktree being added or removed, `fetch --prune`, a push)
fail instead of waiting. A rebase in a worktree writes that worktree's private state (index, `HEAD`,
`.git/worktrees/<name>/rebase-merge`), content-addressed objects (safe to write concurrently), and, shared, the branch ref when it
finishes, its reflog, and rerere cache entries. The agent between `git rebase` stopping and `--continue` runs no git command that
writes shared state.

**Phases.** `move_branch_onto` is split so its steps can be driven separately, taking a `turn` (a context-manager factory, a no-op by
default so existing callers and tests are unchanged):

| Phase | Under the turn | What it does |
|---|---|---|
| 1 | yes | the fetch and base check where the caller has them; the temporary worktree add when there is no worktree; `git rebase --onto` up to its stop; read the conflicted paths, the replayed paths and `must_keep`; record the branch ref's value |
| 2 | **no** | the agent edits files in the worktree; the pipeline's own checks of the files (reads only, no git write); further rungs, each its own call |
| 3 | yes | read the branch ref and compare it with phase 1; `git rerere forget` for rejected or overridden replays; `git add -A`; `git rebase --continue` (or `--abort` when the move is abandoned); the temporary worktree's ref update and removal; |
| push | yes | `push_with_lease` as now, separately |

`git rerere forget` and the cache write are shared state, which is why they sit in phase 3, and the rebase's own rerere recording in
phase 1 and 3 where git does it.

**Both paths follow it.** The handler: `build_stack_moves` stops wrapping `move` in `at_path` (2807) and passes the turn to
`resolved_move` instead; its push is still `at_path(push_with_lease)`. The in-run restack: `build_restack_onto` is given the turn
(`unit_repo_turn`) and passes it down; today it takes none, so the in-run rebase finish and rerere write become serialized for the first
time, against worktree add and push, for seconds. No code path takes the turn while holding it (UNVERIFIED (4)).

**A branch that moved during phase 2.** At phase 3, under the turn, the pipeline reads the branch ref and the unit's recorded head. When
it is not what phase 1 saw, the pipeline aborts the rebase (under the turn), and the restack is retried once from phase 1 (a new
rebase, a new agent run; rerere has nothing to replay for the abandoned resolution because the rebase never committed it). When the
second attempt finds the branch moved again the unit is held `planned` with cause `restack_deferred` and a note naming the branch and
both heads, and nothing is pushed. The retry does not count as the once-per-run hold. Git's own final ref update may also refuse a
moved ref (UNVERIFIED (1)); that outcome is treated the same way, as a failed continue, and does not rely on git doing it. A moved
*base* is not this case: the base check before the push and `verify_base` catch it as now. A remote branch that moved is the existing
lease refusal (`StaleRemote`), unchanged and not retried.

**A unit with no worktree.** The handler's `cwd = worktree if worktree.exists() else repo` fallback (events.py 1404) is where the
operator's checkout is rebased in: `git rebase` with a branch argument checks the branch out in the directory it runs in. The
temporary worktree replaces that fallback for the move: under the turn, `prepare_detached` (workspaces.py) makes `<root>/<repo>/restack-<branch with
non-alphanumerics as _>` at the branch head on no branch; phase 1 runs `git rebase --onto <new base> <old base>` there on the detached
`HEAD` (not naming the branch, so git's refusal for a branch checked out elsewhere does not apply); the agent works in it; at phase 3 the
pipeline moves the branch ref with `git update-ref refs/heads/<branch> <new head> <old head>` (an explicit compare-and-swap, so the
moved-branch rule above holds with no reliance on git); the tree is removed under the turn. A leftover temporary tree from a crash is
aborted (`rebase --abort`), reset to the branch head and reused, or removed, under the turn at the start of the next restack of that
branch. The name is deliberately not `worktree_path`, so the existence test for a unit's own worktree never mistakes it for one.

**A branch checked out elsewhere.** The detached tree answers git's refusal to rebase it. Moving only the ref is safe when no worktree
has the branch checked out; when one does (the operator's checkout, UNVERIFIED (6)), `update-ref` would leave that checkout's index and
working tree describing the old head. The pipeline lists the worktrees under the turn and does not move the ref in that case: the unit
is held `planned` with `restack_deferred` and a note naming the checkout, and the temporary tree is removed. This is stricter than "only
the ref moves" in the plan and is recommended because the alternative corrupts a person's checkout silently.

**A half-finished rebase.** Every failure between the phases (the agent's refusal, interruption, outage or error, a failed check, a
crash of the step's own code that is caught) ends in `git rebase --abort` under the turn before the exception leaves, as `_abort` does
now. The next run's `prepare_worktree` still refuses a dirty tree. A hard kill of the process in phase 2 is the same exposure as today's
resolver window; nothing here widens it. A scan for a rebase in progress at startup is not added.

**Cost of the change.** The resolver's wall time stops blocking other worktree adds and pushes; a clean move takes the turn for
seconds, as before; the in-run restack takes it where it took none.

## Scope notes

- `docs/architecture.md` states "A restack's rebase runs in the repo's own checkout and holds the turn to the end, conflict resolver
  included": that sentence is replaced, and the in-run restack's turn is added.
- The `abk-config` skill's `session_reuse` comment ("tests/implement/fix/rework/adapt share one session") gains `restack`.
- No setting is added. The ladder is not configurable; `max_adapt_rounds` keeps governing rung c's asks.
