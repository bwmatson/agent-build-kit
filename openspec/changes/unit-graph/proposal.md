# Proposal

## Why

A unit's lifecycle is a graph written as hand-rolled control flow:

- `UnitRunner.run` branches on a recorded step;
- `checkpoint()` and `record_step` persist where it got to;
- `reclaim_stale` puts a unit back after a kill;
- the event handlers reach into the unit store to send a unit back, hold it
  or move it.

That is about a third of the framework's code. All of it is the ordinary
business of a workflow framework.

Moving it onto LangGraph is meant to buy four things:

- less orchestration code of our own;
- a lifecycle that reads, and is drawn, as a graph;
- a framework other contributors and agents already know;
- observability per step.

The agents are unchanged: they are still reached through `AgentRuntime`.

## What Changes

The design is agent-build-kit's `docs/unit-graph.md`; it is the reference for
every group below.

- **One LangGraph thread per unit**, `thread_id` the unit id.
  - The nodes are `prepare`, `tests`, `implement`, `review`, `rework`,
    `adapt`, `unit-test`, `e2e-test`, `verify_base`, `push`, `open_pr`,
    `await_review`, `held`, `satisfied` and `failed`.
  - Each wraps the callables `wiring.build_runner` already builds, so no
    agent, git or forge logic is rewritten.
- **Checkpoints in SQLite** (`AsyncSqliteSaver`, WAL) in the state directory,
  with `durability="sync"` and an explicit msgpack allowlist.
- **Waits are interrupts.** `await_review` and `held` wait for the forge or a
  person, and a usage pause interrupts at a node boundary. None of them holds
  a lock.
- **Events are resume commands.** The poller and `abk requeue` resume a unit's
  thread (`rework`, `base_moved`, `hold`, `merged`, `closed`, `requeue`)
  instead of writing into the store from the side.
- **Choosing what starts is unchanged.** `ready_units` and its limits stay,
  and the scheduler starts threads for new units and resumes threads that
  have something to do.
- **The old engine is removed** once the graph carries every path. Units in
  flight are converted at the switch, and `StoredUnit` loses its in-run
  fields.

## Impact

- **agent-build-kit:** a new `graph/` package. `cli/pipeline.py`'s
  `build_unit`, `_schedule` and `reclaim_stale`, `events.py`, `unit_store.py`
  and `stack_runner.py` (whose control flow goes) all change.
- **Dependencies:** `langgraph` and `langgraph-checkpoint-sqlite` become core
  dependencies, pinned together, bringing `langchain-core`.
- **Installations:** one new file of machine-local state,
  `runs/unit-graphs.sqlite`, to be ignored like the other caches.
