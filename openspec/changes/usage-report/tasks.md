# Tasks

Acceptance: a real unit built through a real agent whose report totals equal the
ledger and the run log's agent calls (group 2).

## 1. [agent-build-kit] [unit-test] Report, summary page and archive roll-up

Needs: agent-usage-capture group 1 merged — the agent records the report reads
Needs: unit-time-accounting group 1 merged — the span records the report reads

Done when `abk report` answers the groupings the spec names, the summary page is
written, and archiving a change keeps its totals.

- [x] 1.1 Test: over a fixture ledger, grouping by unit, change, node, role, model,
      repository and day gives rows whose sums equal the ledger's, with `--since`,
      `--change` and `--unit` filters.
- [x] 1.2 Test: estimates appear in their own column and are excluded from totals
      unless `--include-estimates`; absent figures read as absent; the source shows.
- [x] 1.3 Test: `--json` carries the same rows, and a reported and a gateway figure for
      one call both appear with their difference.
- [x] 1.4 Test: the reader tolerates half-written lines, unknown fields and re-run
      duplicates.
- [x] 1.5 Test: the summary page is regenerated when the store is written, and an
      unwritable page does not fail the write.
- [x] 1.6 Test: archiving a change replaces its detail with one summary per unit and
      the report's totals for it are unchanged.
- [x] 1.7 Implement the reader, `abk report`, `planning.usage_page`, and the archive
      roll-up.
- [x] 1.8 Document the command and the page in `docs/cli.md`, `docs/configuration.md`
      and the `abk-config` skill, and add a changelog entry.

## 2. [agent-build-kit] [e2e-test] [acceptance] A real unit's report matches what it did

Done when one fixture unit built through the real agent runtime reports totals that
equal its ledger records and the sum of its run log's agent calls.

- [x] 2.1 Test (`local_stack`): build one unit through the real agent runtime; the
      report for it has one agent record per call in its run log, tokens and time that
      sum to the ledger's, and each figure's source is shown.
- [x] 2.2 Write the acceptance run and document how to run it.
