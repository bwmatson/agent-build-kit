# Proposal

## Why

E2e-test is the live-stack marker, 12 to 66 minutes of real agent calls. Every unit whose group is tagged `e2e-test`, and every `[acceptance]` group,
runs the whole marker. Each unit therefore pays for the whole suite and fails on tests it did not touch: five units are failed at e2e-test now, most
of them for tests they never changed. `tier2-failures-in-untouched-tests-are-fixed-once` made those failures cheaper to recover from; this change
stops charging for them in the first place. The suite still has to run, because a unit can break a test it did not touch, so it runs on a
schedule, once, instead of once per unit.

## What Changes

- **A unit runs its own e2e-test tests.** New setting `e2e_unit_scope`: `own` (default) or `full`, set for a repo at `repos.<name>.tests.e2e_unit_scope` or for all repos at `limits.e2e_unit_scope`; the repo's value wins. Under `own` an e2e-test unit runs only the e2e-test
  tests its branch added or changed against the base, found the way unit-test finds the tests it repeats, through the toolchain's own selection of tests
  by identifier and the same marker. A unit that adds or changes none runs no e2e-test, takes no lock, and its log and status line say that no e2e-test
  test ran: it is not a pass of the suite. `full` is today's behaviour. A run that cannot be narrowed (a toolchain with no selection by identifier,
  a repo that runs e2e-test through its dev stack script, a list of tests that cannot be read) runs the whole marker and says why.
- **Failures are unchanged.** A failing own test fails the unit. The base run, the pre-existing classification, the record and the fix change work
  as before on the failures they are given.
- **The suite runs on a schedule.** New setting `e2e_schedule`: `weekly` (default), `daily`, `monthly` or `off`, set for a repo at `repos.<name>.tests.e2e_schedule` or for all repos at `limits.e2e_schedule`; the repo's value wins. The due check, the open-run check and `off` are each per repo. When it is due for a repo
  that has e2e-test units and no scheduled change of that repo is open, a round writes the change `scheduled-e2e-<repo>-<date>`, as `fix-failing-*`
  changes are written: no model, one group, `Acceptance: none`, priority 3, no code, no pull request. Due is read from the dates in the names of
  the repo's earlier scheduled changes, open and archived; nothing new is stored.
- **A scheduled unit builds nothing.** It goes straight to e2e-test, runs the whole marker whatever the scope setting is, on a tree identical to its
  base. A pass ends it satisfied, with no pull request, and the change archives. A failure is pre-existing by definition (no base run is made), is
  recorded, gets its one fix change, and parks the unit on it; the unit runs the whole marker again when released.
- **Tracked as normal work.** The unit shows in `abk status`, holds a place under `limits.max_units_in_progress`, waits for the e2e-test lock like any
  unit, and starts only when the usage guard lets a unit start.

## Impact

- agent-build-kit: `config.py` (two settings, each a `limits` default and a `tests` override, and their enums), `pipeline/wiring.py` (`E2eSession`: the scope decision, the narrowed commands,
  the base-run skip for an identical tree), `graph/nodes.py` (the `e2e-test` node's no-run outcome; `prepare` and `after_e2e` for a scheduled unit,
  ending in the satisfied outcome), a new module for the schedule (naming, due, the change written), `cli/pipeline.py` (`has_work`, the round,
  the dry-run preview), the status line, `docs/configuration.md`, `docs/architecture.md`, the `abk-config` and `abk-pipeline` skills, the changelog.
- It builds on the merged code of `tier2-failures-in-untouched-tests-are-fixed-once` (the record, `ensure_fix`, `wait_on_preexisting`, the park) and
  `tier2-lock-wait-holds-the-unit`; nothing in them is modified. `tier2-waits-on-open-base-failure-fixes` is amended in the same stroke so its gate
  applies only to full-scope runs, and waits on group 1 of this change for the scope decision it reads.
- Priority 1: the failed e2e-test units wait on group 1.
