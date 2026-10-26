# Tasks

Acceptance: none — removing a command is proved by the suite and a search for its name; tier-1 tests prove it.

Priority: 5

## 1. [agent-build-kit] [tier1] The temporary backfill command is removed

Needs: usage-cost-and-context-are-recorded group 3 merged — the requirement this removes is added to the main specs when that change is archived

Done when `abk usage backfill-costs` and the `usage` command group are gone, a legacy row still reads as legacy, and nothing refers to the command.

- [x] 1.1 Test: `abk usage` is not a command, and a ledger with a row that has no `cost` object still reads it as legacy and does not sum it
      as incremental; a row with the basis `backfilled` and a summary marked `cumulative_summed` still load.
- [x] 1.2 Remove the usage command module and its registration, its tests, and any helper only it used, keeping those the roll-up or the
      report also use.
- [x] 1.3 Remove the command's section from `docs/cli.md` and reword the architecture document's mention of it, search the repository for the
      command's name to leave no reference, and add a changelog entry that says it was removed and what stays.
