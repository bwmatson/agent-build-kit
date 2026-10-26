## REMOVED Requirements

### Requirement: A temporary command repairs legacy cost rows once

**Reason**: The command was written to repair a ledger whose cost figures were session running totals. It has been applied on the installation that had
one, and a second run reports no legacy rows, so it is no longer needed.

**Migration**: Nothing to migrate. Rows it wrote carry the basis `backfilled` and summaries it marked carry `cumulative_summed`; both are still read, and a
row with no `cost` object is still read as legacy and never summed as incremental.
