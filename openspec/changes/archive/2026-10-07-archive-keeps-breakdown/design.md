# Design

## The summary line

Existing fields stay (`kind`, `at`, `unit`, `change`, `repo`, `measured`, `estimated`, the time
buckets, `sources`, `difference`). New: `breakdown`, a list of items. An item has the row fields (the
measured and estimated figures, agent, checks, slot-wait and pause-wait milliseconds, the
gateway-minus-reported difference) and `node`, `role`, `model`, `runtime`, `usage_source`. Items
are keyed by node, role, model and source; the list is ordered by that key so equal input gives
equal output.

Wait spans carry a node and no role or model: they attach to that node's agent item, or to an item
for the node with the role and model `(none)` when the node made no agent call. The review wait is
read from the unit store at report time and is not in the breakdown.

## Invariant

The top-level figures equal the sum of the items. The roll-up asserts it before writing; a test
pins it. Equal sums keep the totals and every per-unit, per-change, per-repo and per-day view
identical to today.

## The reader

For a summary line with a breakdown the reader emits one entry per item, with the node, role and
model from the item and the unit, change, repo and time from the line, and does not also emit the
total. A summary without one yields today's single entry, whose node, role and model read as an
archived-without-breakdown label, so a ledger written before this change loads and totals.

## Re-rolling

The roll-up already folds an existing summary into the unit's group. With breakdowns it merges items
by key and sums them, so rolling a change twice gives the same line. A summary with no breakdown
merged with new detail for the same unit becomes one item keyed with the archived-without-breakdown
label.

## Size

A unit's breakdown is a few items of a few hundred bytes each; growth is bounded by distinct keys,
not by calls.

## The one-time clean-up

Not code. The ledger is a machine-local file the installation owns: the five summaries written before
this change (five units, 44 calls) are removed from it by hand, after a backup copy, with the ledger's
lock held, leaving every other line byte-identical. The reports and the summary page then no longer
list those changes. Nothing in the framework depends on them.

## Out of scope

Rebuilding a breakdown for old summaries (the data is gone), the review wait, and the summary page's
layout.
