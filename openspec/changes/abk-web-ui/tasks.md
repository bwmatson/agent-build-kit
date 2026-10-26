# Tasks

Acceptance: group 10 runs `abk serve` over a scratch installation with a real Claude and a real ACP
agent, reads a unit, streams a live step, chats when paused, starts a session and runs an action.

Priority: 4

## 1. [agent-build-kit] [unit-test] `abk serve` and the read API

Done when a loopback server answers the pipeline, unit, history, logs, usage and live endpoints from
the stores, read-only, and units are addressed as `change/N`.

- [x] 1.1 Test: the server binds the loopback address only and refuses a request through any other.
- [x] 1.2 Test: the unit endpoint returns effective state, cause and note, history entries, base,
      branch, pull request, dependencies and merge gates with their states, and the review round,
      for units in each state; the address is `/api/units/<change>/<n>`.
- [x] 1.3 Test: the log endpoint returns a run's lines from a byte offset, marks a run with no
      outcome line live, survives a file removed between polls, and converts the clock to UTC.
- [x] 1.4 Test: the usage endpoint returns the report builder's JSON for each grouping and filter,
      equal to `abk report`'s; the ledger is read by line and an unparsable last line is skipped.
- [x] 1.5 Test: a read leaves the unit store, ledger, logs and checkpoint database unchanged, and an
      unknown field in `units.json` does not fail a read.
- [x] 1.6 Add the `serve` command, the read API, the live stream and the readers.
- [x] 1.7 Document `abk serve` in `docs/cli.md` and `docs/architecture.md`, and add a changelog entry.

## 2. [agent-build-kit] [unit-test] The UI shell and the pipeline, unit and usage pages

Done when the built UI shows the overview, a unit's status, history, logs and usage, and the usage
report, in a list, header, outlet and chat-panel layout.

- [x] 2.1 Test: the overview, unit and usage pages render from recorded API answers for units in
      each state, with the cause and the held-by shown from the record.
- [x] 2.2 Test: the logs tab groups lines by node, follows a live run, and shows a reply in full.
- [x] 2.3 Test: the unit route uses `change/N` and a link, a title and an action record show the same
      name.
- [x] 2.4 Build the front end (React, Vite, Tailwind, router, charts), the shell, the three pages and
      the build step that ships it in the package; lint it as the other front ends are.
- [x] 2.5 Document the pages and how to build the front end.

## 3. [agent-build-kit] [unit-test] The unit log keeps the agent's words whole

Independent: it changes how the run log is written and read, and nothing the server builds on.

Done when a unit's log holds replies and commands in full and the journal is unchanged.

- [x] 3.1 Test: a multi-paragraph reply is written to the unit's log with indented continuation
      lines and to the journal as one clipped line, for the Claude and the ACP runtime.
- [x] 3.2 Test: a log with continuation lines and an older clipped log both parse, and each
      continuation line is attributed to its reply.
- [x] 3.3 Keep the full text for the unit log in both runtimes, and teach the log reader about
      continuation lines.
- [x] 3.4 Update `docs/architecture.md`'s run log description and add a changelog entry.

## 4. [agent-build-kit] [unit-test] Local records for every metric

Independent: it adds records at existing emit sites and reads nothing from the server.

Done when ticks, pauses, review rounds, check failures and unit outcomes are appended locally and
survive archiving.

- [x] 4.1 Test: with telemetry off, a tick, a pause, a review round, a check failure and a unit
      outcome each append a record with the fields its metric carries.
- [x] 4.2 Test: archiving a change rolls up its usage lines and leaves these records.
- [x] 4.3 Test: durations and counts derived from the records equal the figures the emit sites give
      the exported instruments.
- [x] 4.4 Add the records at the emit sites and exempt them from the roll-up.
- [x] 4.5 Document the records in `docs/architecture.md` and add a changelog entry.

## 5. [agent-build-kit] [unit-test] The metrics page and its two sources

Done when the page lists every metric and uses Prometheus and Tempo or local files, saying which.

- [x] 5.1 Test: the catalogue lists every instrument the telemetry module defines, so a new
      instrument appears without an edit.
- [x] 5.2 Test: with a fake Prometheus answering, charts use windowed sums; with it down, the same
      metrics come from local records and the page says so.
- [x] 5.3 Test: the shipped dashboard's queries use windowed sums for delta data.
- [x] 5.4 Add the metric source interface, both sources, the proxy, the page and the dashboard fix.
- [x] 5.5 Document the metrics page and add a changelog entry.

## 6. [agent-build-kit] [unit-test] The ACP runtime records and resumes its session

Independent: it changes the runtime and the unit's session record, and nothing in the server.

Done when an ACP step's session id is recorded and resumed where the agent can load it.

- [x] 6.1 Test: an ACP step records the session id for its unit and node when the session starts.
- [x] 6.2 Test: against an agent declaring session loading, a resume loads the recorded session;
      against one that does not, it starts a new session and the log says so.
- [x] 6.3 Record the id, read the agent's capability, load the session on resume.
- [x] 6.4 Update `docs/agent-runtimes.md` and add a changelog entry.

## 7. [agent-build-kit] [unit-test] Every agent interaction is recorded whole

Done when each run and chat turn is written to a unit transcript as it streams, in one shape for both
runtimes, with a bounded size and retention.

- [x] 7.1 Test: a Claude step's events (text, reasoning, tool calls and results, usage, stop) are
      appended to the unit's transcript with the time, node, round, session id and source as they
      arrive, from recorded stream output.
- [x] 7.2 Test: an ACP step's updates are recorded in the same shape, including tool calls and results,
      from recorded wire output.
- [x] 7.3 Test: a tool result over the configured size is cut with a marker giving its original length;
      a chat turn is recorded with the source marked chat in the same sequence.
- [x] 7.4 Test: only the configured number of the most recent runs per unit is kept, and a change's
      transcripts are removed with its run logs on archive.
- [x] 7.5 Test: the replay builds the history for the agent tab across runs and chat turns, tool calls
      included, and for an unrecorded session falls back to the runtime's own history and reports where
      tool calls are unavailable.
- [x] 7.6 Write the recorder in both runtimes, the settings for result size and runs kept, the removal
      at archive and the replay.
- [x] 7.7 Document the record in `docs/architecture.md` and add a changelog entry.

## 8. [agent-build-kit] [unit-test] The session bridge, chat and sessions page

Needs: abk-web-ui group 6 — the unit's ACP session must be recorded for the bridge to find it

Done when the agent tab streams a live step, accepts turns when paused under a lease, starts new
sessions, and the sessions page lists and forks them.

- [x] 8.1 Test: Claude and ACP messages map to AG-UI events for text, reasoning, tool calls and
      results, plan and usage updates, and stop reasons, and a loaded history maps to a snapshot.
- [x] 8.2 Test: a running step is streamed and input is refused; once it ends a turn takes the lease,
      a tick does not start a step while it is held, and release or page close returns the unit.
- [x] 8.3 Test: a session whose id is held by a running editor process is read-only, and forking
      starts a new session without writing to the first.
- [x] 8.4 Test: a permission request waits for the browser and is denied when the page closes.
- [x] 8.5 Test: a new session starts in a unit's worktree for the chosen runtime and model.
- [x] 8.6 Test: a session started elsewhere is listed, resumed in place when no process holds it,
      forked when one does, and an ACP session the agent cannot load is shown read-only and continued as
      a new seeded session with the page saying so.
- [x] 8.7 Test: a turn can carry attachments (a file, a line range, the hunk and the selected text),
      the prompt sent to Claude and to the ACP agent contains them, and the composer shows each as a
      removable chip.
- [x] 8.8 Write the bridge, the lease, the live-process check, the new and fork paths, the sessions
      page and the agent tab; settle the chat client question with a spike.
- [x] 8.9 Document the chat rules in `docs/architecture.md` and add a changelog entry.

## 9. [agent-build-kit] [unit-test] Unit actions

Done when requeue, hold, release and approve work from a unit's page through the CLI's code.

- [x] 9.1 Test: each action calls the CLI's function under the store's lock with the real hooks, logs
      the actor, and is refused with the CLI's reason where the CLI would refuse.
- [x] 9.2 Test: the buttons are disabled with that reason for a running unit.
- [x] 9.3 Add the action endpoints and the buttons.
- [x] 9.4 Document the actions and add a changelog entry.

## 10. [agent-build-kit] [unit-test] Approve from the UI and the command line

Done when approve is one function, `approve_unit`, behind both the UI's action and `abk approve <unit>`.

- [x] 10.1 Test: the UI's approve and `abk approve <unit>` call the same `approve_unit`, which records an
      `approved` decision for the unit's current round in the review store at the head the unit's pull
      request has then; the head is stored with the decision, and a decision recorded before it read as
      before.
- [x] 10.2 Test: approve is refused, with a reason, for a unit with no pull request or no head and for a
      round that already has a decision, in the UI as a disabled action and on the command line as a
      failing exit status; nothing is recorded.
- [x] 10.3 Test: approving merges nothing, pushes nothing and calls no vote on the host (the forge is
      untouched), and `abk approve` prints the unit, the head and the round it recorded.
- [x] 10.4 Add `approve_unit` and the `abk approve` command, add the head to the stored decision, and
      make the UI's approve action call it in place of the refusal.
- [x] 10.5 Document `abk approve` in `docs/cli.md` and the action in `docs/architecture.md`, and add a
      changelog entry.

## 11. [agent-build-kit] [e2e-test] [acceptance] The UI over a real scratch installation with a real Claude

Split: claude_code

Needs: tier2-tests-are-tagged-by-runtime group 18 — parked until the live tests are tagged by runtime and the drift test guards them, so an ACP test that cannot run (the model backend is out of budget) is held instead of failing

Done when a real run with a real `claude` shows the pipeline, a live step, its recorded history, a chat turn when paused, a
new session, a continued session and an action working together, and the walk is one runtime-neutral helper the ACP group
reuses. This group is the Claude half of the former single acceptance test; group 12 is the ACP half. Estimate: about 200
changed lines.

- [x] 11.1 Test (`local_stack`, `CLAUDE_CODE_PARAMS`): extract `walk_unit_through_review(scratch, api, runtime)` into
      `tests/integration/` support, neutral to the runtime (no `runtime_*` tag of its own), and use it in a Claude test over a
      scratch installation with a real Claude: read a unit's page, stream a live step with the composer disabled, see its
      recorded history with tool calls, chat once it ends and see the unit resume from its node after release, start a new
      session, and requeue a failed unit.
- [x] 11.2 Test (`local_stack`, `CLAUDE_CODE_PARAMS`): over the same scratch installation, continue a session started
      elsewhere with a real Claude (resumed in place when no process holds it, forked when one does).
- [x] 11.3 Write the acceptance run and document how to run it, including that the ACP half is group 12.

## 12. [agent-build-kit] [e2e-test] [acceptance] The UI over a real scratch installation with a real ACP agent

Split: acp

Needs: abk-web-ui group 11 — the ACP test uses the `walk_unit_through_review` helper group 11 extracts

Done when a real run with a real ACP agent shows the same walk as group 11 through the same helper. This group is
ACP-only on purpose and is held while the ACP split is held; it never carries a Claude test. Estimate: about 150 changed
lines.

- [ ] 12.1 Test (`local_stack`, `RUNTIME_PARAMS` used only here, in an ACP group; no module-level `runtime_acp` mark): over a
      scratch installation with a real ACP agent, call `walk_unit_through_review(scratch, api, runtime)` with the ACP runtime
      and the ACP-specific expectations: a live step with the composer disabled, its recorded history with tool calls, a chat
      once it ends and the unit resuming from its node after release, a new session, and, for a session the agent cannot
      load, one shown read-only and continued as a new seeded session with the page saying so.
- [ ] 12.2 Document how to run the ACP half in the acceptance run's documentation from task 11.3.
