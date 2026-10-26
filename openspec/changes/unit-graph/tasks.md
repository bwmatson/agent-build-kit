# Tasks

Every group's builder reads agent-build-kit's `docs/unit-graph.md` first: it is
the design these tasks implement, and where they disagree, ask in the pull
request rather than guess.

## 1. [agent-build-kit] [unit-test] The graph engine's skeleton, behind a seam

Needs: acp-runtime-adapter group 4 — it is still reshaping the runtime, the
review step and the e2e-test path this change wraps, and starting before it has
merged would mean porting a moving target.

Done when a `UnitEngine` seam runs a unit on the classic engine by default or
on the graph engine with `ABK_ENGINE=graph`, the graph engine has its state
model, checkpointer and compiled graph, and a thread survives a process
restart — with no node doing a step's real work yet and nothing changed for an
installation that does not opt in.

- [x] 1.1 Test: with no setting, `build_unit` runs the classic engine and every
      existing scheduling and runner test passes unchanged.
- [x] 1.2 Test: with `ABK_ENGINE=graph`, a unit gets a thread named by its id in
      `<state_dir>/unit-graphs.sqlite`, and a thread interrupted in one process
      resumes in another at the same node.
- [x] 1.3 Test: a process killed while a node runs leaves the thread resumable
      at that node.
- [x] 1.4 Test: a checkpoint holding every type of the `UnitRun` state loads
      with the msgpack allowlist in force, and a type left off the list fails
      the test.
- [x] 1.5 Add the `UnitEngine` seam, its registry and the `engine`/`ABK_ENGINE`
      setting, with the classic engine wrapping `UnitRunner`.
- [x] 1.6 Add `graph/`: the `UnitRun` model, the node-name enum, the SQLite
      checkpointer with `durability="sync"` and the allowlist, and the compiled
      graph with every node named in the design and none of their work.
- [x] 1.7 Add `langgraph` and `langgraph-checkpoint-sqlite` as dependencies,
      pinned together, and document the setting in `docs/configuration.md` and
      the `abk-config` skill.
- [x] 1.8 Compare agent-build-kit's `docs/unit-graph.md` with what this group
      built — the nodes and edges, the state fields, the event table, the
      durability and concurrency notes, the testing section — and change
      whatever no longer matches, in this same pull request. If nothing differs,
      leave the document alone and say so in the pull request description.

## 2. [agent-build-kit] [unit-test] The build path in the graph


Done when, on the graph engine, a unit is prepared, its tests and
implementation are written, it is reviewed and reworked until approved, unit-test
passes, its base is checked, its approved commit is pushed and its pull request
opened — reaching the same outcomes as the classic engine for the same inputs.

- [x] 2.1 Test: the classic runner's build-path scenarios, ported against the
      graph engine with the same injected fakes, reach the same outcome, state,
      pull request and commits.
- [x] 2.2 Test: each node re-run after a kill does nothing it already did —
      no second commit, push or pull request.
- [x] 2.3 Test: node progress lines reach the unit's run log and each node is a
      span carrying the unit id.
- [x] 2.4 Implement `prepare`, `tests`, `implement`, `review`, `rework`, `unit-test`,
      `verify_base`, `push` and `open_pr` over `wiring.build_runner`'s callables,
      with the edges between them.
- [x] 2.5 Compare agent-build-kit's `docs/unit-graph.md` with what this group
      built — the nodes and edges, the state fields, the event table, the
      durability and concurrency notes, the testing section — and change
      whatever no longer matches, in this same pull request. If nothing differs,
      leave the document alone and say so in the pull request description.

## 3. [agent-build-kit] [unit-test] The remaining paths in the graph


Done when, on the graph engine, adapting onto a moved base, e2e-test, a satisfied
unit, review escalations and holds, spent review rounds and moved bases each
reach the same outcomes as the classic engine.

- [x] 3.1 Test: the classic runner's scenarios for adapt, e2e-test, satisfied,
      escalations, holds, spent rounds and moved bases, ported against the graph
      engine, reach the same outcomes.
- [x] 3.2 Implement `adapt`, `e2e-test`, `satisfied`, `failed` and the routes into
      `held`, with the edges between them.
- [x] 3.3 Compare agent-build-kit's `docs/unit-graph.md` with what this group
      built — the nodes and edges, the state fields, the event table, the
      durability and concurrency notes, the testing section — and change
      whatever no longer matches, in this same pull request. If nothing differs,
      leave the document alone and say so in the pull request description.

## 4. [agent-build-kit] [unit-test] Waits and events as interrupts and resume commands


Done when, on the graph engine, a unit in review or held waits in an interrupt
holding no lock, the poller's events and `abk requeue` resume its thread, a
usage pause interrupts at a node boundary and is resumed by a later tick, and
a killed run is resumed rather than requeued.

- [x] 4.1 Test: a unit waiting in review holds no branch lock or repo turn and
      takes no slot, and an event for it is delivered at once.
- [x] 4.2 Test: rework (comment, changes requested, label, failing check,
      conflict), moved base, hold, merge, close and requeue each resume the
      thread into the node the design names; an event during a node is
      delivered after it returns.
- [x] 4.3 Test: a usage refusal before an agent step interrupts with the
      guard's resume time; a tick on which the guard allows resumes it there.
- [x] 4.4 Test: a run killed mid-node is resumed at that node by the next tick,
      with no requeue to `planned`.
- [x] 4.5 Test: an agent node records the agent's session id in the thread's
      state as soon as the runtime reports it; a node killed mid-agent and
      resumed by the next tick resumes that session with a prompt saying the
      process was interrupted and to re-read the worktree before trusting its
      memory, rather than starting a new one.
- [x] 4.6 Test: a recorded session the runtime cannot resume (a runtime
      without session resume, a missing session, a refusal) falls back to
      running the node from its start in a new session, and says so in the run
      log.
- [x] 4.7 Implement the `await_review` and `held` interrupts, the event handlers
      as resume commands, usage pauses as interrupts, session capture and
      resume on the runtime seam, and the scheduler starting and resuming
      threads.
- [x] 4.8 Compare agent-build-kit's `docs/unit-graph.md` with what this group
      built — the nodes and edges, the state fields, the event table, the
      durability and concurrency notes, the testing section — and change
      whatever no longer matches, in this same pull request. If nothing differs,
      leave the document alone and say so in the pull request description.

## 5. [agent-build-kit] [unit-test] The switch: the graph is the only engine


Done when the units in flight are converted to threads, the graph is the only
engine, and the classic control flow, its resume bookkeeping and the seam are
gone — with every ported scenario still passing.

- [x] 5.1 Test: a store holding units at each resume step, with waiting
      feedback, in review and held, converts to threads positioned at the
      nodes the design names, and each then proceeds as it would have.
- [x] 5.2 Test: every scenario ported in groups 2–4 passes with no engine
      setting at all.
- [x] 5.3 Convert units in flight at the first tick on the new version.
- [x] 5.4 Remove `UnitRunner`'s control flow, `resume_from`, `checkpoint()`,
      `record_step`, `starting_step`, `reclaim_stale`'s requeue, `StoredUnit`'s
      in-run fields, the `UnitEngine` seam and its setting, and the tests of
      removed code.
- [x] 5.5 Update `docs/architecture.md`, `docs/unit-graph.md` (status: built, and anything else that no longer matches what was built),
      the `abk-pipeline` skill and the changelog.

## 6. [agent-build-kit] [e2e-test] [acceptance] One real unit built end to end through the graph

Needs: acp-tests-follow-the-graph-log group 1 merged — the live-agent suite must already pass on the graph's log, so this unit proves only its own test


Done when a real unit is planned, built, reviewed, pushed and opened through
the graph, then resumed into rework by a real review comment and pushed again.

- [x] 6.1 Test: against a scratch planning repo and code repo with the real
      agent runtime, a unit's thread runs to its pull request, waits in review,
      is resumed by a comment the test posts through the forge fake, reworks,
      and pushes again; the thread is gone once the test merges it.
- [x] 6.2 Compare agent-build-kit's `docs/unit-graph.md` with what this group
      built — the nodes and edges, the state fields, the event table, the
      durability and concurrency notes, the testing section — and change
      whatever no longer matches, in this same pull request. If nothing differs,
      leave the document alone and say so in the pull request description.
