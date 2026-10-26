# Proposal

## Why

The pipeline is observed through `abk status`, `abk report`, generated pages, per-unit run logs, the
journal and Grafana, and its agents are driven from an editor. Answering "why is this unit where it
is, what did it say, what did it cost, can I talk to the agent that built it" takes five tools. The
agent's own words are clipped to one line in the unit log, and several metrics (tick duration, review
rounds after a thread ends, pauses) cannot be rebuilt without the telemetry stack.

## What Changes

- **`abk serve`:** a long-running local server (loopback only) with a read API over the unit store,
  the usage ledger, run logs and the checkpoint store, and a bundled web UI built with the React,
  Vite, Tailwind and CopilotKit stack an existing AG-UI chat front end uses.
- **Pages:** the pipeline overview; a unit page addressed by its own name (`change/N`) with status,
  cause and history, logs, usage, review and agent tabs; a usage report page; a metrics page; a
  sessions page.
- **Whole agent words in the unit log:** `says:` text and tool-call commands are kept in full in the
  unit's run log; the journal keeps its one-line form.
- **Local metric records:** ticks, pauses, review rounds, check failures and unit outcomes are
  appended to local files, so every metric the pipeline exports can be rebuilt without Prometheus.
- **Metrics from two sources:** Prometheus and Tempo when reachable, local files otherwise, with
  the source shown.
- **ACP session continuity:** the ACP runtime records the session id and resumes a session when
  the agent supports it, as the Claude runtime does.
- **Every agent interaction recorded whole:** each run and chat turn is written to a unit transcript as
  it streams, in one shape for both runtimes, so the agent tab can show the history with tool calls.
- **Chat with the unit's agent:** a live step is streamed read-only; the composer enables when the
  session is paused; a turn holds a lease so the tick does not run the unit meanwhile; new sessions
  can be started; sessions started elsewhere can be continued here, in place when idle and as a fork when
  an editor holds them. What a turn may change, and how a commit enters the pipeline, is `ui-chat-editing`.
- **Unit actions:** requeue, hold, release and approve, through the same code and locks as the CLI.
  Approve is one function behind both the UI and a new `abk approve <unit>`; it records the approval in
  the review store and never merges.

## Impact

- agent-build-kit: new `serve` command and package, `run_log`, the telemetry/ledger emit sites, the
  ACP runtime and the unit graph's session bookkeeping, plus docs and a bundled front end.
- Follow-on changes: `ui-chat-editing` (live edits from chat and the commit that adopts them),
  `ui-review` (diff view and feedback), `local-forge` (review without a remote pull request). Moving an existing Node AG-UI chat backend to a Python bridge is a separate change in
  that repository and has no dependency on this one.
