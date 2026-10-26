# Design

## The reader

One module reads the ledger (tolerant of half-written lines and unknown fields),
keeps one record per unit, node, round and session, joins unit metadata from the
store, and produces rows for any grouping. The command, the page and the metrics
roll-up all use it.

## Output

A table by default, `--json` for tools. Columns: group key, calls, input, output,
cache read, cache write, cost, agent time, checks time, slot wait, pause wait, review
wait, and a source column showing whether the figures were reported, from the gateway
or estimated. Estimates appear as a separate column and are omitted from sums unless
`--include-estimates`. Where reported and gateway figures both exist, the difference is
shown in `--json` and flagged in the table when large.

## Page

`planning.usage_page` (default `docs/unit_cost.md`), written best-effort from the
store's write hook. A failed write never takes down the store write, as for the graph
page.

## Archive

`archive_ready_changes` calls the roll-up before it removes the run logs: each unit's
records collapse into one `summary` record with the totals and the source mix, the
detail lines for that change are dropped, and the report reads summaries and detail
alike.

## Acceptance

An e2e-test group builds one fixture unit through the real agent and asserts the
report's totals for it match the ledger and a hand-sum of the run log's agent calls.

## Out of scope

Metrics export (`usage-telemetry-rollup`).
