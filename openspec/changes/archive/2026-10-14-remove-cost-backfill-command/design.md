# Design

## What goes

The `usage` command group has one command, so the whole module goes, with its entry in the list of command modules and its tests. The
command's section in the command reference goes, and any sentence in the architecture document that points a reader to the command is reworded
to say the figures were repaired once and the repaired rows carry the basis `backfilled`.

Helpers that only the command used go with it; a helper the roll-up or the report also uses stays. The builder finds which by searching for
callers, and says which it removed in the changelog entry.

## What stays

The reader's tolerance for an old row stays: a row with no `cost` object reads as `legacy` and is never summed as incremental. A ledger
from another installation, or an old backup, can still hold such rows, and reading it must not overstate cost. The values `backfilled` and
`cumulative_summed` stay in the set of cost bases, since rows and summaries already carry them.

## The requirement it removes

The requirement that describes the command is removed from the usage-accounting capability. It is added to the main specs when
`usage-cost-and-context-are-recorded` is archived, which is why this change waits for that change's last group to merge; a removal of a
requirement that is not yet in the main specs would fail at archive.

## Done condition

The ledger on the installation that ran it has no legacy rows and the command's own dry run said so. This change fulfils the follow-up
recorded with `usage-cost-and-context-are-recorded`.
