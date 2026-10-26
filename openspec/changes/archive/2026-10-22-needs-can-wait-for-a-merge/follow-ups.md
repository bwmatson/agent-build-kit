## From `needs-can-wait-for-a-merge/1`

- src/agent_build_kit/pipeline/units.py:598 — `edge_kind` takes a `repos` argument it never reads; its docstring admits this ('kept in the signature for a rule that needs one; none does yet'). Every caller (`waiting_on`, `merge_parents`, `gate_sent_back`) still has to fetch `config.active().repos` to pass it.
- src/agent_build_kit/pipeline/units.py:607 — `edge_kind` and `merge_loaded` read `gated_requeue`, `merge_sha` and `merged_tick` with `getattr` because those fields exist only on `StoredUnit` while the functions take `Unit`.
- src/agent_build_kit/pipeline/units.py:667 — Outside a tick, `waiting_on` calls `loaded_code.current()` on every call, and that reads and parses `tick.json` each time. Status and the diagram call `waiting_on` once per unit.

## From `needs-can-wait-for-a-merge/3`

- In test_old_merged_lines_over_the_recorded_units_delay_no_unfinished_unit, the recorded changes have no tasks.md in the Replan workspace. That makes `link_needs` leave merge_needs alone, so 'the migration line prints nothing' holds trivially. The wait comparison is the assertion that carries the test. A comment saying so would help the next reader.
