# Proposal

## Why

The ledger (`agent-usage-capture`, `unit-time-accounting`, `gateway-usage-attribution`)
holds the facts. Nothing reads them back, so the answer to "why did that change cost
so much" is still a guess.

## What Changes

- **`abk report`** groups by unit, change, node, role, model, repository and day, and
  sums tokens by kind, cost and the time buckets: agent, checks, waiting for a slot,
  paused for usage and waiting in review. Filters `--since`, `--change`, `--unit`;
  `--json`. Estimates are in their own column and left out of totals unless asked for;
  the source of each figure is shown; cost is labelled notional where the plan is a
  subscription.
- **A generated summary page** (`docs/unit_cost.md` by default, path from
  `abk.yaml`) is rewritten when the unit store is written, as the graph page is, with
  per-change totals and the most expensive units.
- **Archive keeps totals.** When a change is archived its detail records are rolled
  into one summary record per unit and then pruned, so a long-running installation's
  ledger does not grow without bound and old changes still report.
- **One real run is the acceptance:** a unit built through a real agent whose report
  totals equal the ledger and the run log's agent calls.
