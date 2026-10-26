## From `a-unit-in-a-held-split-is-not-started/1`

- The builder could not write to the change's design.md. A person should resolve its UNVERIFIED item about replanning with the text the builder gave: `UnitStore.upsert` gives an unstarted unit the split of the fresh plan, and keeps the stored split of a started unit. tests/pipeline/test_unit_store_split.py now pins this behaviour.
- `split_note` in planner.py is a public name, but only `_in_flight_line` uses it and no test imports it. Making it private (`_split_note`) would match the helpers beside it.

## From `a-unit-in-a-held-split-is-not-started/2`

- The change's spec (split-start-gate 'The reason' scenario), proposal, design and tasks 2.4, 3.1, 3.3 and 4.1 in the planning repo still say "waiting for tier 2 split <name>" and `abk tier2 check`. Those were written before the repo-wide test-kinds rename. Update them to "e2e-test split" and `abk e2e-test`, so the later units (status line, diagram legend, skill-text test) assert the wording the code and changelog now use, not the old one.

## From `a-unit-in-a-held-split-is-not-started/4`

- tests/cli/test_e2e_check_split_declaration.py:101 — The new real-git test no longer tells the merge base apart from the default branch's tip. `touched_tests` drops deleted tests, so a test that only main added shows up as deleted in a `main..branch` tree diff and is left out either way. If `unit_own_tests` diffed against `repo.default_branch` again, this test would still pass.
- src/agent_build_kit/pipeline/wiring.py:3283 — `own_test_ids` puts `touched_tests` and `_ids_for` together for the check. The run's three call sites (wiring.py:1058/1097, 1235/1245, 2293/2301) still put them together inline.
