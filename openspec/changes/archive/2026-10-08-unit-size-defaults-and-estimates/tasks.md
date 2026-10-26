# Tasks

Acceptance: none — configuration defaults, a prompt and bookkeeping inside the pipeline;
tier-1 tests prove them.

## 1. [agent-build-kit] [tier1] Smaller defaults, a defined estimate, and the actual size

Done when a workspace with no sizes set plans with floor 400 and ceiling 750, the planner is
told what an estimate counts, and each unit's actual size is recorded and compared.

- [x] 1.1 Test: with no limits configured the floor is 400 and the ceiling 750; a workspace
      that sets either keeps it; a ceiling at or below the floor fails to load naming both.
- [x] 1.2 Test: the planner's instructions contain the definition of an estimate (all
      files, deletions counted for removing groups, excluding generated files, estimate high
      when unsure) and the configured floor and ceiling.
- [x] 1.3 Test: opening a pull request records the unit's actual lines from the host's
      totals less generated files; a push after a rework updates it; a unit with no pull
      request has none.
- [x] 1.4 Test: an actual size over the ceiling is logged, marked on the graph page and
      listed by the status, and the unit is not blocked.
- [x] 1.5 Change the defaults, rewrite the planner's estimate paragraph, add
      `actual_lines`, the generated-file patterns, and the log, page and status output.
- [x] 1.6 Update `docs/configuration.md`, the `abk-config` skill, `docs/architecture.md`
      and the `abk-authoring` skill where they state 500 or 1000, and add a changelog
      entry.
