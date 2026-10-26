# Proposal

## Why

The ledger and `abk report` answer questions about a unit. Trends (is review getting
slower, which model burns the window, how long do units wait for slots) are better
watched on a dashboard over time, and the stack the pipeline already exports to has
one.

## What Changes

- **New instruments from the ledger**, with bounded attributes only (repository, tier,
  node, role, model, wait bucket, source): cost, tokens by kind, and the wait buckets
  as histograms. Unit ids and change names stay out of metrics.
- **The pipeline dashboard gains panels** for them, in the framework's own dashboard
  (`abk-pipeline-dashboard`), pushed through the platform's intake.
- **Per-unit detail stays local**, in the ledger and the report.
