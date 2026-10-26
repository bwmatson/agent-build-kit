# Proposal

## Why

The cost the ledger records for a Claude Code call is the session's running total, not the call's own spend: the
`result` event's `total_cost_usd` rises across a session's calls and never falls. Every sum over it counts a session's
earlier calls again in each later one. In this installation's ledger the agent rows sum to $558.51 while the sessions'
increments sum to $266.34, so the recorded cost is overstated by 52%. The same figure feeds `abk report`, the summary
rows written at archive, the web UI's usage view and the `abk.agent.cost` counter. Session reuse made resumed calls
common, which is why the error became large. The ACP runtime already subtracts a per-session baseline for a resumed
call; the Claude Code runtime does not.

Separately, nothing records how much of the model's context window a step used. Whether a step is near the limit, how
fast a session fills, and which steps add the most are the questions that decide when a fresh session or a smaller step
is the fix, and today they cannot be answered from the ledger.

## What Changes

- **Every agent row carries one `cost` object** with the call's own spend (`incremental_usd`), the session's running
  total as the runtime reported it (`cumulative_usd`), how the incremental figure was obtained (`basis`, a closed set)
  and the runtime's own figure where a gateway's is used instead (`reported_usd`). The flat `cost_usd` and
  `reported_cost_usd` fields are no longer written. Every sum and the cost counter read `incremental_usd`.
- **Old rows are read as `legacy`** and never summed as if they were incremental; the report counts and lists them and
  shows their total apart.
- **The baseline for a resumed call** is kept on the recorded session, with the ledger's last row for the session as a
  fallback and an honest `unknown` when neither exists, never the total.
- **A temporary command, `abk usage backfill-costs`**, repairs the ledger once (dry run by default, backup, lock, atomic
  rewrite, idempotent). Its removal is recorded in `follow-ups.md` and is deliberately not a task group.
- **Every agent row carries one `context` object**, in tokens: where the step started, where it ended, how much it
  added, its peak, how many times it compacted and the model's window size. The report gains `--context`, telemetry
  gains gauges and a counter, and a step that ends above a configured share of the window logs a warning.

## Impact

- agent-build-kit: the Claude Code and ACP runtimes, the recorded session in graph state, the ledger record and reader,
  the usage report, the metrics export and the web UI's usage view, a new `usage` subcommand, configuration and the
  documents that describe the ledger.
- Installations: the ledger's historical cost figures are wrong until the backfill is run; archived summaries and
  already exported counters cannot be corrected (see the design).
- No change to scheduling: nothing decides from the context figures in this change.
