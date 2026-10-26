# Design

## Context

`TestTier` (`model.py`) is the one type for a test kind; the heading reader takes its tags from `TEST_KIND_TAGS` (every member's value), so
a new member is accepted automatically. What reads the kind otherwise is a handful of places, and each is either "is it e2e" (unchanged by a
new member that is not e2e) or "are two kinds the same" (joins, calibration, the unit tier), which is where this change works.

## Decisions

- **A pure label.** Every branch on the kind tests for `E2E_TEST` alone, so a unit of the new kind falls to the unit-test path with no
  other code. No `integration_test_*` setting exists; the `unit_test_*` settings apply. The pytest `integration` marker and
  `tests/integration/` mean something else (a real <redacted> or a throwaway container) and the label does not imply them.
- **Width order.** One helper beside `TestTier` returns the widest of some kinds by the order `unit-test` < `integration-test` < `e2e-test`;
  the unit tier (`pipeline/units.py`), the drift check for a started unit's tags (`cli/pipeline.py`) and a join's surviving unit use it.
- **Join compatibility** is "both e2e, or neither": the check in `pipeline/joins.py` and the planner prompt's line "same repo and same
  tier" change together, since the prompt is what the planner is told and the check is what refuses a plan.
- **Calibration** keys a ratio by repository, kind and flag. The key uses the pooled kind (`integration-test` as `unit-test`), so neither
  the stored ratio nor its label changes for existing data and no new class of samples starts empty.
- **Review classes and floors** are the unbuilt review changes' concern. The class `<repo>/unit-test` and the floors are written there to
  treat the new kind as `unit-test`; this change owns no review code.

## Test harness

Fake units and temporary `tasks.md` files from the existing helpers (`tests/factories.py`, `tests/cli/replan_driver.py`); no new fake.

## Contracts

Nothing crossing a repository boundary is widened. The one widening is a value `integration-test` that a state file may now hold; the same
abk reads and writes it, and a reader without this change refuses it as an unknown kind, which is the existing behaviour for an unknown
value. Nothing is narrowed afterwards.

## Risks

- **Groups already tagged `unit-test` stay as they are**; nothing retags them. The label only appears where an author writes it.
- **The rename change rewrites files these groups edit.** The first group waits for the rename's group 4 (which converts
  `pipeline/work_graph.py`, and follows its group 3, which converts the other pipeline modules), and the later groups follow the first, so
  they edit those files on their final names. The rename's groups 5 and 6 in turn wait for the first group here, because their tests and
  texts name the new kind.
