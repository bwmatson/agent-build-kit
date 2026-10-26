# Proposal

## Why

`abk usage backfill-costs` was written to repair a ledger whose cost figures were session running totals recorded as if they were each call's
own. It was documented as temporary. It has been applied with `--apply` on the installation that had a ledger to repair, and a second run
reports no legacy rows and changes nothing. A command that is no longer needed is code, tests and documentation to keep in step with a ledger
format it will never meet again.

## What Changes

- **The command is removed:** `abk usage backfill-costs`, and with it the `usage` command group, which holds nothing else.
- **What stays:** the reader that reads a row with no `cost` object as legacy and never sums it as incremental, and the `backfilled` and
  `cumulative_summed` values, because rows written by the command and summaries it marked are still in ledgers and must still be read.
- **The documentation says it is gone:** the command's section is removed from the command reference, and the changelog records the removal.

## Impact

- agent-build-kit: the usage command module and its registration, the command's tests, `docs/cli.md`, the architecture document's mention of
  the command, and the changelog.
