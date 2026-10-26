## Context

Priority is an integer, 1 to 5, in four places: `PRIORITY_VALUE = [1-5]` in `pipeline/work_graph.py` (its error text says "from 1 (most urgent) to 5"),
`Priority` (an `IntEnum`, `FIX = 1` to `NICE_TO_HAVE = 5`) and the `ge`/`le` bound on `Unit.priority` in `pipeline/units.py`, and prose. `unit_priority`
(`pipeline/planner.py`) takes the minimum over a unit's groups; `effective_priority` takes the minimum over the unit and its waiters; `_start_key` and
`_handoff` sort by that number. All of that is numeric and orders 0 first without a change.

## Decisions

- **Add `Priority.EMERGENCY = 0`** and move the `Unit.priority` lower bound to it. The pattern becomes `[0-5]`, and the message says "from 0 (emergency) to 5".
  Nothing else in parsing changes: one line per place, a second line is an error, a line in an unreadable group is an error.
- **No bypass.** The user decided "start first only". Priority 0 changes the sort position and nothing else; `ready_units` and `start_room` read no priority
  when they count room, and the tests pin that.
- **Falsy zero.** A zero priority is the risk of this change. The code read on the main branch has no truthiness test on a priority:
  - `work_graph.validate_tasks`: `priorities.get(current) is None` and `default_priority is None` are identity tests, correct; the group's priority is
    `priorities.get(line, default)` with a sentinel `None` default, correct. A rewrite to `or Priority.NORMAL` would turn 0 into 3.
  - `planner.unit_priority`: `min(found, default=Priority.NORMAL)` is correct; `found` holds 0 and is non-empty.
  - `unit_store._record`: drops the key only when `unit.priority == Priority.NORMAL`, so a 0 is written; it is read back through the model's
    `priority` field, whose default (3) applies only when the key is absent.
  - `unit_store.upsert` copies `existing.priority` for a started unit: a copy, not a test. `set_priority` writes whatever it is given.
  - `cli/pipeline.py`: the log of non-3 priorities and the status reason use `!= Priority.NORMAL` and `urgency < unit.priority`; `min(..., key=priority)`
    is numeric. `abk tags` and the graph page use `!= Priority.NORMAL`.
  - `units.effective_priority`: `min([unit.priority, *waiters])`, correct.
  - No `or 3`, `if unit.priority`, `priority or` or `.get("priority")` was found in `src` (including the serve and web code, which do not read priority).
  The change pins each as a test over a priority of 0, so a later refactor to a truthiness test fails a test.
- **The error range.** `-1`, `6`, `2.5` and `high` stay refused: the pattern is one digit, so `-1` and `10` do not match.
- **Two groups.** The first is the value, the model bound and the zero-safety tests; the second is the scheduling confirmation, display, and text. This change
  is unrelated to the other changes open now and carries no `Needs:` on them.

## Risks

- A 0 in a store read by an older release fails its `ge=1` bound. Priority 0 is not used until a person writes it, and the release that reads it is this one.
