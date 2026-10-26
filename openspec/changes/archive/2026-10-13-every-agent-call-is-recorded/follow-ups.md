## From `every-agent-call-is-recorded/1`

- tests/agent_call_sites.py:72 — `_bound_requests` keys only on plain `ast.Assign` to an `ast.Name`, and `named` is a set of names. So one name bound to two `AgentRequest(...)` constructions in the same function counts both as recorded if either is passed to `recorded`. An annotated assignment (`x: AgentRequest = AgentRequest(...)`) is never bound, so it is always flagged.

## From `every-agent-call-is-recorded/2`

- web/src/test/recorded/usage-unit.json:147 — The fixture's `total` was not updated when the two overhead rows (plan $0.25, track_health $0.125) were added, so the fixture's rows plus overhead no longer add up to its total. The real report counts overhead in its total.
