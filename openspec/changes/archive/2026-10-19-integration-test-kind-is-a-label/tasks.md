# Tasks

Acceptance: none — the label changes no behaviour a consumer drives: it is read from a heading, carried on a unit, compared when units are joined and keyed in calibration, and each is a unit-test over fake units, temporary `tasks.md` files and stores; nothing here touches the stack.

Priority: 3

## 1. [agent-build-kit] [tier1] The integration-test tag is accepted and listed

Done when a heading tagged `[integration-test]` is read as the third `TestTier`, a plan and a stored unit may hold the kind, `abk tags` and `abk status` show it as its own kind, every message listing the tags names all three, `[integration]` and `tier3` are still refused, and `[acceptance]` on it is refused. Estimate: about 150 changed lines.

Needs: test-kinds-are-unit-test-and-e2e-test group 4 — that group converts `pipeline/work_graph.py`, which this one edits, so the heading reader is changed once on its final names

- [x] 1.1 Test: in `tests/pipeline/test_work_graph_integration_test_tag.py`, a `tasks.md` with one group each of `[unit-test]`, `[integration-test]` and `[e2e-test]` reads as the three kinds in order with no error and no notice; `[integration]` and `[tier3]` are each refused with a message naming `unit-test`, `integration-test` and `e2e-test`; `[integration-test] [acceptance]` is refused naming `e2e-test`.
- [x] 1.2 Test: in `tests/pipeline/test_planner_integration_test_kind.py`, a planner reply whose unit has `"tier": "integration-test"` parses to that kind, and a unit with an unknown `tier` is refused as before; in `tests/pipeline/test_unit_store_integration_test_kind.py`, a stored unit of that kind is written and read back with the value `integration-test`.
- [x] 1.3 Test: in `tests/cli/test_tags_and_status_integration_test.py`, `abk tags` prints a group tagged `[integration-test]` as `[integration-test]` with no deprecation line, and `abk status` prints a stored unit of that kind with its kind and in none of the lists for `e2e-test` units (held, lock, scheduled).
- [x] 1.4 Test: in `tests/test_model_test_tier.py`, `TestTier` has exactly the members `UNIT_TEST`, `INTEGRATION_TEST` and `E2E_TEST` in that order with the values `unit-test`, `integration-test` and `e2e-test`, and `TEST_KIND_TAGS` lists the same three values.
- [x] 1.5 Add `INTEGRATION_TEST = "integration-test"` between the two members of `TestTier` in `model.py` and update its docstring; the heading reader takes it from `TEST_KIND_TAGS`; make the tag listing in `abk tags` and `abk status` and each message that names the accepted tags use the enum's values, and keep every branch for the stack testing `TestTier.E2E_TEST` alone.

## 2. [agent-build-kit] [tier1] A unit takes the widest kind of its groups, and joins treat integration-test as a unit-test

Done when a unit built from several groups takes the widest of their kinds, a join accepts a unit-test with an integration-test and still refuses an e2e-test with the others, the surviving unit of a join takes the widest kind, the tag check of a started unit compares against the widest kind of its groups, and the planner's prompt and schema example name the three kinds. Estimate: about 230 changed lines.

- [x] 2.1 Test: in `tests/pipeline/test_units_widest_kind.py`, a unit built from `unit-test` and `integration-test` groups is `integration-test`, from groups that include an `e2e-test` is `e2e-test`, from one kind alone is that kind, and the order of the groups does not matter.
- [x] 2.2 Test: in `tests/pipeline/test_joins_integration_test.py`, a `unit-test` group joins onto an `integration-test` unit and the reverse, a `unit-test` unit joins onto an `integration-test` unit, the survivor of each is `integration-test`, and an `e2e-test` unit or group is refused with each of the others in both directions.
- [x] 2.3 Test: in `tests/pipeline/test_planner_prompt_kinds.py`, the prompt's join rule says the same repository and compatible kinds and names which kinds go together, and its schema example reads `unit-test|integration-test|e2e-test`.
- [x] 2.4 Test: in `tests/cli/test_tag_drift_widest_kind.py`, a started unit of kind `integration-test` carrying a `[unit-test]` group and an `[integration-test]` group reports no difference between its stored kind and its tags, and retagging the second to `[unit-test]` reports one naming the unit.
- [x] 2.5 Add a function beside `TestTier` in `model.py` that returns the widest of some kinds by the order `unit-test`, `integration-test`, `e2e-test`; use it where `pipeline/units.py` sets a unit's kind (replacing the choice of `e2e-test` or `unit-test`), in the survivor of a join in `pipeline/joins.py`, and in the stored-kind comparison of `abk replan`'s tag check in `cli/pipeline.py`.
- [x] 2.6 Change the kind comparison in `pipeline/joins.py` for a unit and for a group to "both `e2e-test`, or neither", and word the join rule and the schema example in the planner prompt in `pipeline/planner.py` to match.

## 3. [agent-build-kit] [tier1] Calibration pools integration-test with unit-test

Done when a ratio is keyed by repository, the pooled kind and the flag with `integration-test` counted as `unit-test`, so samples of both feed one ratio and a unit of either is calibrated by it, in the stored kind, the planned kind and the join ceiling check. Estimate: about 90 changed lines.

- [x] 3.1 Test: in `tests/pipeline/test_unit_size_pooled_kind.py`, `kind_of` gives the same `Kind` for a stored unit of `unit-test` and one of `integration-test` in one repository with the same flag, the calibration over merged units of both is one ratio built from all their samples, and the `Kind` of an `e2e-test` unit stays apart.
- [x] 3.2 Test: in `tests/pipeline/test_planner_calibration_pooling.py`, a planned unit of `integration-test` is checked against the ceiling with the ratio the same unit tagged `unit-test` gets, and `plan_kind` returns the same `Kind` for both.
- [x] 3.3 Test: in `tests/pipeline/test_joins_calibration_pooling.py`, a join of an `integration-test` unit and a `unit-test` unit is checked against the ceiling with the ratio of a join of two `unit-test` units.
- [x] 3.4 Add a function beside `TestTier` that gives the kind a ratio is keyed by (`integration-test` as `unit-test`, the others as themselves), and use it where `pipeline/unit_size.py` builds a `Kind` from a stored unit and where `pipeline/planner.py` builds one from a planned unit.

## 4. [agent-build-kit] [tier1] The tests that list the kinds name the third

Done when every test that enumerates the test kinds covers `integration-test` as well, so the suite pins the listings, the pooled values and the refusals the earlier groups added. Each of these passes once groups 1 to 3 have landed. Estimate: about 120 changed lines.

- [x] 4.1 Update `tests/graph/test_remaining_paths.py` (the test that parametrizes a unit's kind where a clean move onto the base is pushed, near line 1101) to add the `integration-test` value, which is pushed and not held exactly as `unit-test` is.
- [x] 4.2 Update `tests/serve/test_metrics_ledger_test_kind_values.py` so a ledger line whose kind is `integration-test` is its own label, neither merged into `unit-test` nor changed, and an old spelling still maps to its new one.
- [x] 4.3 Update `tests/pipeline/test_unit_store_test_kind_values.py` (which parametrizes over `list(TestTier)`) so it also asserts the third member is among them and that the table of old spellings holds none for it.
- [x] 4.4 Update `tests/pipeline/test_work_graph.py` (the test of unknown tags, near line 94) to add `integration` to the refused names and assert the message names all three tags.
- [x] 4.5 Update `tests/config/test_test_kind_settings_aliases.py` so a test pins that no setting is named for `integration-test` and the `unit_test_*` settings are the ones read for a unit of that kind.
- [x] 4.6 Update `tests/test_compat_names.py` so `integration-test` is returned unchanged as a tag and a value, is not an old spelling, and the table of old and new spellings holds no entry for it.
- [x] 4.7 Update `tests/pipeline/test_work_graph_test_kind_tags.py` to read the three new tags in order, to assert an unknown tag's message names all three, and to assert `abk tags` and `abk check` print no notice for `[integration-test]`.
