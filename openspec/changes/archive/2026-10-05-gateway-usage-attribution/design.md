# Design

## First task: can the agent take its key from the environment

The spawned ACP agent must read its gateway key from an environment variable at
start. The first task checks that against the runtime in use, with the result noted
here. If it cannot, this change delivers the seam and the client and the runtime
declares the source unavailable.

## The seam

`UsageSource` with `begin(request) -> env, handle` and `finish(handle) -> Usage`.
The gateway client implements it with minting at `begin` and a spend read at
`finish`; the key is revoked in a `finally`. Failure to mint or read never fails
the run: the record falls back and says why.

## Attribution

Alias `abk:<unit>:<node>:<round>:<run>`, so concurrent runs never share a key. The
spend read is by key, so there is no time-window guessing across concurrent units.

## Cross-check

Where both the agent and the gateway report, the record keeps the agent's figures as
`reported` and the gateway's as `gateway`, and the report shows the difference.

## Settings

`ABK_GATEWAY_URL` and `ABK_GATEWAY_MASTER_KEY` through `settings.py`. Neither set:
skipped silently. A master key with no URL, or an unreachable gateway: one warning.

## Out of scope

The record and ledger (`agent-usage-capture`) and any report. Until that change has
merged, this change records through the same writer behind a small interface of its
own and is reconciled when both exist.
