# Proposal

## Why

`abk report --by node` shows a `(summary)` row holding 44 calls, about $34 and about 12,000 seconds
of agent time, roughly 43% of the total. It is work from changes that have been archived. Archiving
replaces a change's usage detail with one summary line per unit that holds only totals; the node,
role and model of each call are discarded, so a report grouped by any of them cannot split that work
and files it under `(summary)`. The share grows with every archived change, and the node, role and
model views get less useful over time.

## What Changes

- **A summary keeps a breakdown.** The line that replaces a unit's detail keeps every field it has
  today and gains a breakdown with one item per node, role, model and source, each holding that
  group's calls, tokens, cost and the agent, checks, slot-wait and pause-wait times. Time spent
  waiting at a node with no agent call is kept under that node.
- **Reports use it.** For a summary with a breakdown the report reads the items, not the total, so
  `--by node`, `--by role` and `--by model` split archived work as they split live work, and there is
  no `(summary)` row. Totals are unchanged.
- **Always written, from now on.** The roll-up never writes a summary without a breakdown. A summary
  from an older ledger, which has none, still loads as it does today; re-rolling merges by key.
- **The old summaries are removed from this installation's ledger** (a one-time action, not part
  of the code change): their detail is gone, nothing can rebuild their split, and they are not
  wanted.
