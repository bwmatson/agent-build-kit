# Proposal

## Why

The ledger is the only place spend is counted: the report, the usage page, the metrics, the usage
estimate and its calibration all read it. Only the unit graph's own steps (`tests`, `implement`, `review`,
`rework`, `fix_checks`, `adapt`) write a row. Every other call that sends a prompt to an agent spends
the same account's window and is invisible to all of them: the conflict resolver that runs when a restack
conflicts, the planner on every tick that plans, the track runs (health, improve, recommend, propose), init's research
and proposal runs, the policy probe, the login refresh and every chat turn from the web UI. An analysis of how a conflict is
resolved could not say what the resolver costs, because it leaves no row. The framework already promises
"every agent call writes exactly one ledger row"; that promise holds only for calls made through the unit
graph, and nothing stops a new call site from breaking it again.

## What Changes

- **One helper builds the row** for any agent call, from the same figures the unit steps record (tokens by
  kind, cost and its cumulative baseline, context, turns, duration, session, source, outcome). The unit
  steps use it too, so there is one writer of agent rows.
- **Every site records under its own node name**: `restack`, `plan`, `track_health`, `track_improve`,
  `track_recommend`, `track_propose`, `init_research`, `init_propose`, `policy_probe`, `login_refresh`, `chat`
  and `chat_commit`. `unit` is blank where there is none; `change` and `repo` are filled when known.
- **The `restack` node** records the conflict resolver: one row per resolver call, with the unit being moved
  as `unit`, its model, tokens, cost and duration. It is the node the single-session conflict change
  builds on.
- **The reader keeps each such row as its own call**, and the usage estimate and its calibration never count
  a blank unit as a unit.
- **`abk report` and the usage page show a `pipeline overhead` line per node** for rows with no unit.
- **A guard test** finds every construction of an agent request, and every direct run on a runtime, that
  does not record, and fails unless the site is on an allowlist with a reason; the last group empties
  the allowlist.

Not included: any change to the row's schema, to what the usage guard admits, or to how a call is
priced; no per-call gateway key for the new sites.
