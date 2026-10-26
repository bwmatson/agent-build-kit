# Design

## Reading the result event

`ResultEvent` stays `extra="ignore"` and gains an optional `usage` model with the
four token counts, plus `total_cost_usd`, `duration_ms`, `num_turns`, `session_id`.
The first task is a live check of the field names against a real event, and of how a
`--resume`d session reports usage (cumulative or per call), before the ledger
asserts that records sum.

## The result and the call site

`AgentResult` gains `usage: Usage | None`, `cost_usd`, `turns`, `duration_ms`,
`session_id`, `usage_source`. `AgentRequest` gains `on_result`, called by the
runtime with the finished result, as `on_session` is called with the session. The
graph's agent step binds it with the unit, node and review round it knows, which
avoids changing the closure that returns the text.

## Sources

`reported`: the agent's own figures. `estimated`: when an ACP agent reports none,
tokens approximated from prompt and response sizes and flagged. `none`. A
`gateway` source is a separate change (`gateway-usage-attribution`) that
plugs in beside these.

## The record

One line of JSON per call: kind `agent`, UTC `at`, unit, change, repo, tier,
node, round, role, model, runtime, session id, resumed, the usage fields,
`usage_source`, outcome. A pydantic model, read with `extra="ignore"` so older
lines load. The reader keeps the last line per (unit, node, round, session) key.

## Writing

Append-only with short lines, opened for each write, in the state directory. Any
`OSError` is caught, reported once per process and dropped. Concurrent unit threads
append whole lines, which are atomic at this size on a local filesystem.

## ACP drift

At initialize the runtime reads the agent's advertised capabilities and records
whether usage is offered. The ACP library version is pinned. A contract test
replays recorded payloads with usage, without it and with an unknown extra field.

## Out of scope

Time and waits (`unit-time-accounting`), reporting (`usage-report`), the gateway
source.
