# Tasks

Acceptance: none — runtime capture and a ledger writer; tier-1 tests over recorded
payloads and the ledger prove it. `usage-report` carries the end-to-end acceptance
for the whole accounting chain.

## 1. [agent-build-kit] [tier1] One ledger record per agent call

Needs: abk-telemetry group 2 merged — builds on the agent result fields and the traced runtime wrapper that group adds

Done when each agent call leaves one record in the ledger with the usage its
runtime reported and where it came from, a re-run counts once, and nothing the
ledger does can fail a run.

- [x] 1.1 Test: a recorded Claude result event with usage parses into the tokens,
      cost, turns, duration and session; an event missing any of them, or carrying
      an extra field, still parses.
- [x] 1.2 Test: a call on the Claude runtime appends a record naming the unit,
      node, round, role, model and runtime with source `reported`; a failed call
      records its figures too.
- [x] 1.3 Test: an ACP call whose response carries usage records it as
      `reported`; one without records `none` with absent figures, or flagged
      estimates when estimation is on.
- [x] 1.4 Test: replayed ACP payloads (with usage, without, with an unknown
      extra field, malformed) never fail the run; the malformed one degrades and
      logs once.
- [x] 1.5 Test: the same node and round written twice (a re-run, a resumed
      session) is counted once by the reader; older lines without new fields load.
- [x] 1.6 Test: an unwritable ledger drops the write, reports once and leaves
      the run's outcome unchanged.
- [x] 1.7 Check against a live Claude result which usage fields exist and how a
      resumed session reports usage, and note the finding in the design.
- [x] 1.8 Add the usage model to the result event, the fields to the agent result
      and `on_result` to the request, fill them in both runtimes, record the
      agent's usage capability at initialize, pin the ACP library, and write the
      record from the graph's agent step.
- [x] 1.9 Add the ledger to the planning repo's ignore rules in the templates
      `abk init` writes, document it in `docs/architecture.md` and
      `docs/configuration.md`, and add a changelog entry.
