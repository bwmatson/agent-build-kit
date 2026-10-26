# Tasks

Acceptance: none — ledger bookkeeping and a report; tier-1 tests over fixture ledgers prove it.

## 1. [agent-build-kit] [tier1] The roll-up keeps the breakdown

Done when an archived change's summary carries a breakdown that the report uses, the totals are
unchanged, and an older summary still loads.

- [x] 1.1 Test: archiving a change with agent calls at several nodes, roles and models, plus wait
      spans, writes one summary per unit whose breakdown has one item per node, role, model and
      source, and whose items sum to the top-level figures.
- [x] 1.2 Test: the report by node, by role and by model after archive splits the archived work as
      before it was archived, with no row standing for archived work as a whole, and the totals by
      unit, change, repository and day equal those before archive.
- [x] 1.3 Test: a node with only wait spans keeps its wait under that node (an item with role and model
      `(none)`).
- [x] 1.4 Test: rolling a change up twice leaves the file unchanged; a summary with no breakdown
      merged with new detail for the same unit keeps its totals under one labelled item.
- [x] 1.5 Test: a ledger holding an old summary without a breakdown loads and totals, shown under
      one labelled row in the node, role and model views.
- [x] 1.6 Add the breakdown to the summary record and the roll-up (key, order, sum check, merge),
      read it in the report, and keep the existing archive tests green.
- [x] 1.7 Update the module documentation, `docs/architecture.md` and `docs/cli.md`, and add a
      changelog entry.
