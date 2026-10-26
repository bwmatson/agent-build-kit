# Design

The design is agent-build-kit's `docs/unit-graph.md`. It covers:

- the boundary;
- who holds what;
- the graph and its nodes;
- the state model;
- events as resume commands;
- durability and idempotency;
- usage pauses;
- concurrency;
- observability;
- moving the units in flight;
- testing.

Each group's builder reads it first. What follows is only how the work is cut
into units, and what each group may rely on.

## Order

1. **Skeleton behind a seam.** A `UnitEngine` seam lets `build_unit` run a
   unit on either engine: the classic `UnitRunner`, the default, or the
   graph. Group 1 lands the state model, the checkpointer and an engine that
   compiles and resumes, with no node doing real work yet. Nothing changes for
   a running installation.
2. **The build path** in the graph: build → review ⇄ rework → unit-test → push →
   open the pull request. The stack runner's scenarios for that path are
   ported as tests against the graph engine.
3. **The remaining paths:** adapt, e2e-test, satisfied, escalations and holds,
   spent rounds, moved bases. Their stack runner scenarios are ported too.
4. **Waits and events:**
   - `await_review` and `held` interrupts;
   - the event handlers become resume commands;
   - usage pauses become interrupts;
   - resuming a thread replaces `reclaim_stale`'s requeue.
5. **The switch.** Units in flight are converted, the graph becomes the only
   engine, the seam and the classic control flow are removed, and the docs are
   updated.
6. **Acceptance:** one real unit built end to end through the graph.

## Session capture and resume

An agent node's state carries `session_id`. `AgentRuntime` reports the id as
soon as the agent starts: the Claude runtime from the stream's first event, the
ACP runtime from `session/new`. A runtime that can continue a session declares
it (`supports_session_resume`) and takes the id on the next request; `claude -p
--resume <id>` is that for the Claude runtime, `session/load` for an ACP agent
that offers it. One that cannot declares nothing and every resume starts a new
session.

On a resume after a kill, the node's prompt is the interruption note ("the
process was interrupted; re-read the worktree and the branch before relying on
what you remember") instead of the original prompt, since the session already
holds it. The worktree is never reset to what the session remembers: the
leftovers the reclaim path commits today are on the branch, and the agent is
told to look.

Fallback is a node run from its start in a new session, as before this
requirement, so a lost session file, a changed CLI version or a refusal costs
only the saving. The id is scoped to its node and thread: it is cleared when
the node completes, so a later node never continues an earlier node's
conversation.

The saving is mainly for long sessions (`implement`, `adapt`, long reworks); a
short step costs nearly the same to resume as to restart, since the prompt cache
has expired by then.

## What each group may rely on

- Groups 2–4 run only with the graph engine selected (`ABK_ENGINE=graph`), so
  the classic engine keeps the pipeline building until group 5.
- Group 5 removes `resume_from`, `checkpoint()`, `record_step`,
  `starting_step` and `StoredUnit`'s in-run fields. The ported tests from
  groups 2–4 are what proves nothing was lost; classic-only tests that test
  removed code go with it.
- `units.json` keeps every field a person or the scheduler reads. The unit
  graph page and `abk status` are unchanged throughout.
