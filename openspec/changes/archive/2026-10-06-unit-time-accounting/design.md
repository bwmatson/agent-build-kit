# Design

## Spans

The graph's node wrapper already runs around every node; it records `started` and
`ended` (UTC) and the monotonic duration, and writes one `span` record when the node
returns or raises. A node that is interrupted writes its record at the interrupt with
`waited=usage_pause`, and the resume writes the wait's end.

## Slot wait

The tick's pool submit records the time a ready unit enters its queue; the worker
records the time it acquires the unit's branch lock. The difference is the slot wait,
written as a span with `waited=slot`.

## Review wait

Derived, not stamped by a new hook: an `in_review` interval in the unit's history
runs until its next state. The report splits it by pull request check results when
the poller has them, otherwise it is `review`.

## Tier 1 commands

`build_tier1` already times each command with a monotonic clock for its log line; it
also passes the duration to the recorder.

## The record

Shares the ledger and the record model with `agent-usage-capture` (kind `span`). Until
both have merged, this change writes through its own small writer with the same line
shape; the second to merge reconciles the two.

## Out of scope

Aggregation, and token figures.
