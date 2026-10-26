# Proposal

## Why

An ACP agent may report no usage, and an estimate is only an estimate. The
gateway in front of the model already logs exact tokens and cost per request. If
each agent run is given a key of its own, the gateway's records for that key are
the run's true usage, whatever the agent reports.

## What Changes

- **A key per agent run.** Before a run, the framework asks the gateway to mint a
  short-lived key whose alias names the unit, node and round, and hands it to the
  spawned agent through its environment. It is revoked afterwards.
- **The run's usage is read back** from the gateway's spend and token totals for
  that key, and recorded with source `gateway`. It outranks `estimated` and, for an
  agent that reports usage, is kept beside it as a cross-check.
- **Optional and generic.** The gateway URL and master key are settings; with none
  set the source is skipped and nothing else changes. The framework names no
  gateway product in its code paths beyond the small client it needs, behind a seam.
- **Where the agent cannot take a key from its environment,** the source is
  unavailable for that runtime and the record falls back, with a log line.
